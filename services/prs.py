from Crypto.Signature import PKCS1_v1_5 as PKCS1_v1_5_sig
from Crypto.Cipher import PKCS1_v1_5 as PKCS1_v1_5_ciph
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import unpad
from Crypto.Hash import HMAC, SHA256
from Crypto.PublicKey import RSA
from Crypto.Cipher import AES
from playwright.sync_api import sync_playwright
from tempfile import TemporaryDirectory
from base64 import b64encode, b64decode
from zipfile import ZipFile
from pathlib import Path
from io import BytesIO
import xml.etree.ElementTree as et
import requests
import string
import random
import time
import json
import fitz
import lib
import re

service = "prs"

# It probabily is such a happy time to maintain this pearson's legacy codebase
reader_etext_clientid = "t1txmB9oRay3yK5aIQxsS28Z9T19xMLM"
hawkkeyid = "GPgRTj6fOI"
hawkkey = "UTpkeCcbmFwsz0DAGZRhnkGuQGoYVz6a"
appid = "54c89f6c1d650fdeccbef5cd"
tenantid = "0a0e20af-1ef3-4650-8f44-48c3bc5f9584"
tenantkey = "9edbf937-3955-4c98-a698-07718a6380df"
rpluszipkey = "sDkjhfkj8yhn8gig"

def getetexttoken(username, password, clientid):
	r = requests.post("https://login.pearson.com/v1/piapi/login/webcredentials", data={"password": password, "isMobile": "true", "grant_type": "password", "client_id": clientid, "username": username}, headers={"User-Agent": "mobile_app"})
	return r.json()

def resolveescrow(escrowticket, clientid):
	r = requests.post("https://login.pearson.com/v1/piapi/login/webacceptconsent", data={"escrowTicket": escrowticket, "client_id": clientid})
	return r.json()

def refreshetexttoken(refreshtoken, clientid):
	r = requests.post("https://login.pearson.com/v1/piapi/login/webtoken", data={"refresh": "true", "client_id": clientid, "isMobile": "true"}, cookies={"PiAuthSession": refreshtoken})
	return r.json()

def getetextuserinfo(userid, etexttoken):
	r = requests.get(f"https://marin-api.prd-prsn.com/api/1.0/users/{userid}", params={"include": "gpsSubscriptions"}, headers={"Authorization": f"Bearer {etexttoken}"})
	return r.json()

def getrplustoken(username, firstname, lastname):
	r = requests.post("https://api-prod.gls.pearson-intl.com/user/session/token", headers={"Authorization": gethawk()}, data={"username": username, "firstname": firstname, "lastname": lastname})
	return r.json()

def getrplususerinfo(rplustoken):
	r = requests.get("https://api-prod.gls.pearson-intl.com/user", headers={"token": rplustoken, "appid": appid})
	return r.json()

def getbookshelf(etexttoken, rplustoken, rplususerid):
	headers = {"Authorization": f"Bearer {etexttoken}"}
	url = "https://marin-api.prd-prsn.com/api/1.0/bookshelf"
	if (rplustoken and rplususerid):
		headers |= {"X-Tenant-Id": tenantid, "X-Tenant-Key": tenantkey, "X-Tenant-Region": "IRE", "X-GAB-Authorization": rplustoken, "X-GAB-UserId": rplususerid}
		url = "https://marin-api.prd-prsn.com/api/1.0/rplus/bookshelf"
	r = requests.get(url, headers=headers)
	return r.json()

def getcdntoken(etexttoken, bookid):
	r = requests.get(f"https://marin-api.prd-prsn.com/api/1.0/products/{bookid}/token", headers={"Authorization": f"Bearer {etexttoken}"})
	return r.json()

def getddk(etexttoken, deviceid):
	r = requests.get(f"https://marin-api.prd-prsn.com/api/1.0/capi/ddk/device/{deviceid}", headers={"Authorization": f"Bearer {etexttoken}"})
	return r.json()

def getbookinfo(etexttoken, xsignature, bookid, productid, deviceid, entitlementsource):
	data = {"productId": productid ,"entitlementSource": entitlementsource, "deviceId": deviceid, "bookId": bookid}
	r = requests.post("https://marin-api.prd-prsn.com/api/1.0/capi/product", data=data, headers={"Authorization": f"Bearer {etexttoken}", "X-Signature": xsignature})
	return r.json()

def getbooktoc(etexttoken, productid, bearer=True, xauth=True):
	headers = {}
	if bearer:
		headers["Authorization"] = f"Bearer {etexttoken}"
	if xauth:
		headers["X-Authorization"] = etexttoken
	r = requests.get("https://prism.pearsoned.com/api/contenttoc/v1/assets", headers=headers, params={"productId": productid})
	return r.json()

def downloadfile(url, progress, total, done, cdntoken=""):
	r = requests.get(url, headers={"etext-cdn-token": cdntoken} if cdntoken else {}, stream=True)
	length = int(r.headers.get("content-length", 1))
	file = b""
	for data in r.iter_content(chunk_size=102400):
		file += data
		progress(round(done + len(file) / length * total))
	return file

def downloadfile_nostream(url, cdntoken):
	r = requests.get(url, headers={"etext-cdn-token": cdntoken})
	return r.content

def getrsakey(key):
	# The keys are base64 decoded twice
	decoded = b64decode(b64decode(key).decode())
	return RSA.importKey(decoded)

def computexsignature(devicephrase, signatureddk):
	rsakey = getrsakey(signatureddk)
	message = devicephrase.encode()
	sha = SHA256.new()
	sha.update(devicephrase.encode())

	signer = PKCS1_v1_5_sig.new(rsakey)
	signature = signer.sign(sha)
	return b64encode(signature).decode()

def computedecryptionkey(securedkey, ddk):
	rsakey = getrsakey(ddk)
	message = b64decode(securedkey)

	sentinel = b64encode(get_random_bytes(16))

	cipher = PKCS1_v1_5_ciph.new(rsakey)
	finalkey = cipher.decrypt(message, sentinel, expected_pt_len=24)
	return finalkey

def decryptfile(file, key):
	iv = file[:16]

	# It's not AES128 key=b64decoded string, it's AES192 key=24-byte string
	obj = AES.new(key, AES.MODE_CBC, iv)
	return unpad(obj.decrypt(file[16:]), AES.block_size)

def getoutlines(item, labels, level):
	subtoc = []
	if item["pageno"] in labels:
		subtoc.append([level, item["title"], labels.index(item["pageno"]) + 1])
	else:
		print("Missing page in the pdf! Incomplete toc!")
	if "children" in item:
		for i in item["children"]:
			subtoc.extend(getoutlines(i, labels, level + 1))
	return subtoc

def zippassword(encryptedpass):
	cipher = AES.new(rpluszipkey.encode(), AES.MODE_CBC, bytes(16))
	return unpad(cipher.decrypt(b64decode(encryptedpass)), AES.block_size)

def gethawkmac(ts, nonce):
	normalizedstring = f"hawk.1.header\n{ts}\n{nonce}\nPOST\n/user/session/token\napi-prod.gls.pearson-intl.com\n443\n\n\n"

	secret = hawkkey.encode()
	h = HMAC.new(secret, digestmod=SHA256)
	h.update(normalizedstring.encode())
	return b64encode(h.digest()).decode()

def gethawk():
	ts = str(int(time.time()))
	nonce = "".join([random.choice(string.ascii_letters) for i in range(6)])
	mac = gethawkmac(ts, nonce)

	return f'ReaderPlus key="{hawkkeyid}", ts="{ts}", nonce="{nonce}", mac="{mac}"'

def cover(token, bookid, data):
	etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken = tuple(token.split("|"))
	if data["type"] == "ETEXT_PDF":
		cdntokenanswer = getcdntoken(etexttoken, bookid)
		r = requests.get(data["cover"], headers={"etext-cdn-token": cdntokenanswer["value"]})
		return r.content
	else:
		r = requests.get(data["cover"])
		return r.content

def refreshtoken(token):
	etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken = tuple(token.split("|"))
	refresh = refreshetexttoken(refreshtoken, reader_etext_clientid)
	if refresh["status"] == "success":
		etexttoken, refreshtoken = refresh["data"]["access_token"], refresh["data"]["refresh_token"]
		etextuserinfo = getetextuserinfo(etextuserid, etexttoken)
		if "error" not in etextuserinfo:
			return "|".join([etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken])

def checktoken(token):
	etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken = tuple(token.split("|"))
	etextuserinfo = getetextuserinfo(etextuserid, etexttoken)
	if "error" not in etextuserinfo:
		return "|".join([etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken])

def login(username, password, rplus=True):
	logindata = getetexttoken(username, password, reader_etext_clientid)
	if "data" not in logindata:
		if len(logindata["message"]) == 10:
			logindata = resolveescrow([logindata["message"]], reader_etext_clientid)
		else:
			return
	etexttoken, etextuserid = logindata["data"]["access_token"], logindata["data"]["userId"]
	etextuserinfo = getetextuserinfo(etextuserid, etexttoken)
	if "id" not in etextuserinfo:
		return

	rplustoken, rplususerid = "", ""
	if rplus:
		rplustokenreply = getrplustoken(username, etextuserinfo["firstName"], etextuserinfo["lastName"])
		if "token" in rplustokenreply:
			rplustoken = rplustokenreply["token"]
			rplususerinfo = getrplususerinfo(rplustoken)
			rplususerid = rplususerinfo["id"]

	return "|".join([etexttoken, etextuserid, rplustoken, rplususerid, logindata["data"]["refresh_token"]])

def library(token, rplus=True):
	etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken = tuple(token.split("|"))
	books = {}
	bookshelf = getbookshelf(etexttoken, rplustoken, rplususerid)
	if "error" in bookshelf:
		return
	for i in bookshelf:
		end = i["product_entitlements"]["end_date"]
		if end:
			try:
				if time.time() > time.mktime(time.strptime(end, "%Y-%m-%dT%H:%M:%S.%f%z")):
					continue
			except ValueError:
				pass
		books[str(i["book_id"])] = {"title": i["book_title"], "cover": i["cover_image_url"], "isbn": i["isbn"], "type": i["product_model"], "prodid": i["product_id"], "author": i["author"], "entitlementsource": i["entitlement_source"], "rplus": rplus, "pwd": i.get("encrypted_password"), "url": i.get("downloadUrl")}
	
	return books

def downloadetext2cite(token, bookid, data, progress):
	pdf = fitz.Document()
	toc = []

	progress(2, "Computing key")
	key, bookinfo = computefinalkey(token, bookid, data)

	progress(7, "Downloading zip")
	if "packageUrl" in bookinfo and "securedKey" in bookinfo:
		basezip = downloadfile(bookinfo["packageUrl"], progress, 46, 7, bookinfo["cdnToken"])
	elif "alternateUrl" in bookinfo:
		basezip = downloadfile_nostream(bookinfo["alternateUrl"], bookinfo["cdnToken"])

	reszip = ZipFile(BytesIO(basezip))

	structure = getbooktoc(token, data["prodid"], False, True)

	margin = "0.4in"
	def parsestructure(children, pdf, page, level, basedir):
		for i in children:
			if i["type"] == "chapter":
				toc.append([level, i["title"].strip(), len(pdf) + 1])
				parsestructure(i["children"], pdf, page, level + 1, basedir)
			elif i["type"] == "slate":
				toc.append([level, i["title"].strip(), len(pdf) + 1])
				page.goto((basedir / i["uri"]).as_uri())
				#advancement = (j + 1) / len(pages) * 62 + 36
				#progress(advancement, f"Printing {j + 1}/{len(pages)}")
				pdfpagebytes = page.pdf(print_background=True, margin={"top": margin, "right": margin, "bottom": margin, "left": margin})
				pagepdf = fitz.Document(stream=pdfpagebytes, filetype="pdf")
				pdf.insert_pdf(pagepdf)

	with TemporaryDirectory(prefix="etext2cite.", ignore_cleanup_errors=True) as tmpdirfull:
		tmpdir = Path(tmpdirfull)
		progress(46, "Extracting")
		for file in reszip.namelist():
			if file.endswith(".bin"):
				fileout = decryptfile(reszip.read(file), key)
				filepath = tmpdir / file
				filepath.parent.mkdir(parents=True, exist_ok=True)
				open(filepath.with_suffix(""), "wb").write(fileout)
			else:
				reszip.extract(file, tmpdir)

		with sync_playwright() as p:
			browser = p.chromium.launch()
			page = browser.new_page()
			parsestructure(structure["children"], pdf, page, 1, tmpdir)
			browser.close()

	progress(98, "Applying toc")
	pdf.set_toc(toc)
	return pdf

def computefinalkey(token, bookid, data):
	decodedjwt = json.loads(b64decode(token.split(".")[1] + "=="))
	deviceid = decodedjwt["deviceid"]

	keys = getddk(token, deviceid)
	xsignature = computexsignature(keys["devicePhrase"], keys["signature-ddk"])
	bookinfo = getbookinfo(token, xsignature, bookid, data["prodid"], deviceid, data["entitlementsource"])
	key = computedecryptionkey(bookinfo["securedKey"], keys["ddk"])

	return key, bookinfo

def downloadetextbook(token, bookid, data, progress):
	progress(2, "Computing key")
	key, bookinfo = computefinalkey(token, bookid, data)

	if "packageUrl" in bookinfo and "securedKey" in bookinfo:
		progress(7, "Downloading encrypted book")
		book = downloadfile(bookinfo["packageUrl"], progress, 81, 7, bookinfo["cdnToken"])
		'''
		i = 1
		while not book:
			progress(7, f"Downloading, try #{i}")
			book = downloadfile(bookinfo["packageUrl"], progress, 81, 7, bookinfo["cdnToken"])
			i += 1
		'''
		progress(88, "Decrypting file")
		decryptedbook = decryptfile(book, key)
	elif "alternateUrl" in bookinfo:
		progress(7, "Downloading book")
		decryptedbook = downloadfile_nostream(bookinfo["alternateUrl"], bookinfo["cdnToken"])

	progress(93, "Opening pdf")
	pdf = fitz.Document(stream=decryptedbook, filetype="pdf")
	
	progress(95, "Fetching toc")
	tocobj = getbooktoc(token, data["prodid"])
	toc = []

	labels = [page.get_label() for page in pdf]
	if "children" in tocobj:
		for i in tocobj["children"]:
			if i["type"] in ["slate", "chapter"]:
				toc.extend(getoutlines(i, labels, 1))
		progress(98, "Applying toc")
		pdf.set_toc(toc)
	
	return pdf

def downloadrpluspdf(url, password, progress):
	progress(2, "Downloading zip")
	bookzip = ZipFile(BytesIO(downloadfile(url, progress, 95, 2)))

	progress(98, "Extracting book")
	finalpassword = zippassword(password)
	pdfpath = next(i for i in bookzip.namelist() if i.endswith(".pdf"))
	pdf = fitz.Document(stream=bookzip.read(pdfpath, pwd=finalpassword), filetype="pdf")

	return pdf

def gentoc(item, level, pages, basedir):
	toc = []
	for li in item.findall("{http://www.w3.org/1999/xhtml}li"):
		ref = li.find("{http://www.w3.org/1999/xhtml}a")
		text, href = ref.text, ref.get("href")
		if href.startswith("https://") or href.startswith("http://") or not href:
			continue
		href = (basedir / href.split("#")[0]).resolve()
		toc.append([level, text, pages.index(href) + 1])
		if sub := li.find("{http://www.w3.org/1999/xhtml}ol"):
			toc.extend(gentoc(sub, level + 1, pages, basedir))
	return toc

def downloadrplusepub(url, password, progress):
	pdf = fitz.Document()
	toc, labels, pages = [], [], []

	progress(2, "Downloading zip")
	bookzip = ZipFile(BytesIO(downloadfile(url, progress, 20, 2)))
	finalpassword = zippassword(password)

	with TemporaryDirectory(prefix="rplusepub.", ignore_cleanup_errors=True) as tmpdirfull:
		tmpdir = Path(tmpdirfull)
		ns = {"xhtml": "http://www.w3.org/1999/xhtml", "ops": "http://www.idpf.org/2007/ops", "opf": "http://www.idpf.org/2007/opf"}
		progress(24, "Extracting zip")
		epubpath = next(i for i in bookzip.namelist() if i.endswith(".epub"))
		bookzip.extract(epubpath, tmpdir, pwd=finalpassword)
		del bookzip
		epubzip = ZipFile(tmpdir / Path(epubpath))

		progress(31, "Extracting epub")
		epubzip.extractall(tmpdir)
		info = et.fromstring(open(tmpdir / "META-INF" / "container.xml", "r", encoding="utf-8-sig").read())
		contentspath = tmpdir / info.find("{urn:oasis:names:tc:opendocument:xmlns:container}rootfiles").find("{urn:oasis:names:tc:opendocument:xmlns:container}rootfile").get("full-path")
		contents = et.fromstring(open(contentspath, "r", encoding="utf-8-sig").read())

		files = {i.get("id"): i.attrib for i in contents.find("opf:manifest", ns).findall("opf:item", ns)}
		spine = contents.find("opf:spine", ns)
		pages = [(contentspath.parent / files[i.get("idref")]["href"]).resolve() for i in spine.findall("opf:itemref", ns)]
		navpath = contentspath.parent / next(i["href"] for i in files.values() if i.get("properties") == "nav")
		
		tocfile = et.fromstring(open(navpath, "r", encoding="utf-8-sig").read())

		tocitem = [i for i in tocfile.find("xhtml:body", ns).findall("xhtml:nav", ns) if i.get("{http://www.idpf.org/2007/ops}type") == "toc"]
		if tocitem:
			print("Your book doesn't have a table of contents!")
			toc.extend(gentoc(tocitem[0].find("xhtml:ol", ns), 1, pages, navpath.parent))

		pagelistitem = next(i for i in tocfile.find("xhtml:body", ns).findall("xhtml:nav", ns) if i.get("{http://www.idpf.org/2007/ops}type") == "page-list")
		labelsdict = {}
		for i in pagelistitem.find("xhtml:ol", ns).findall("xhtml:li", ns):
			ref = i.find("xhtml:a", ns)
			labelsdict[(navpath.parent / ref.get("href")).resolve()] = ref.text

		with sync_playwright() as p:
			browser = p.chromium.launch()
			page = browser.new_page()
			for j, fullpath in enumerate(pages):
				if label := labelsdict.get(fullpath):
					labels.append(label)
				else:
					labels.append(str(j + 1))

				sizematch = re.search(r'content.+?width\s?=\s?([0-9]+).+?height\s?=\s?([0-9]+)', open(fullpath, encoding="utf-8-sig").read())

				page.goto(fullpath.as_uri())
				advancement = (j + 1) / len(pages) * 62 + 36
				progress(advancement, f"Printing {j + 1}/{len(pages)}")
				width, height = str(int(sizematch.group(1)) / 144) + "in", str(int(sizematch.group(2)) / 144) + "in"
				pdfpagebytes = page.pdf(print_background=True, width=width, height=height, page_ranges="1")
				pagepdf = fitz.Document(stream=pdfpagebytes, filetype="pdf")
				pdf.insert_pdf(pagepdf)
			browser.close()

	progress(98, "Applying toc/labels")
	pdf.set_page_labels(lib.generatelabelsrule(labels))
	pdf.set_toc(toc)
	return pdf

def downloadbook(token, bookid, data, progress):
	etexttoken, etextuserid, rplustoken, rplususerid, refreshtoken = tuple(token.split("|"))

	match data["type"]:
		case "ETEXT_PDF":
			pdf = downloadetextbook(etexttoken, bookid, data, progress)
		case "RPLUS_PDF":
			pdf = downloadrpluspdf(data["url"], data["pwd"], progress)
		case "RPLUS_EPUB":
			pdf = downloadrplusepub(data["url"], data["pwd"], progress)
		case "ETEXT2_CITE":
			pdf = downloadetext2cite(etexttoken, bookid, data, progress)
		case _:
			print(f"Unsupported format {data['type']}! Contact the developer to get it added!")
			exit()

	return pdf
