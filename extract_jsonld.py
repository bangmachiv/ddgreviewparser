import json,sys,re,time
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"}
session=requests.Session(); session.headers.update(HEADERS)

BAD_PATTERNS=[r"access denied",r"just a moment",r"checking your browser",r"cf-browser-verification",r"cloudflare",r"captcha",r"human verification",r"enable javascript"]

def valid(html):
    if not html or len(html)<200: return False
    h=html.lower()
    return not any(re.search(p,h) for p in BAD_PATTERNS)

def fetch_requests(url,retries=3):
    last=None
    for i in range(retries):
        try:
            r=session.get(url,timeout=30,allow_redirects=True)
            r.raise_for_status()
            if valid(r.text): return r.text,"requests"
            raise RuntimeError("invalid html")
        except Exception as e:
            last=e; time.sleep(2**i)
    raise last

def fetch_playwright(url):
    with sync_playwright() as p:
        b=p.chromium.launch(headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page=b.new_page(user_agent=HEADERS["User-Agent"])
        page.goto(url,wait_until="networkidle",timeout=30000)
        html=page.content(); b.close()
        if not valid(html): raise RuntimeError("invalid html")
        return html,"playwright"

def repair(t):
    t=t.lstrip("\ufeff")
    t=re.sub(r",(\s*[}\]])",r"\1",t)
    return t

def jsonlds(html):
    soup=BeautifulSoup(html,"html.parser")
    out=[]
    for i,s in enumerate(soup.find_all("script",type="application/ld+json")):
        t=s.string or s.get_text()
        if not t: continue
        try:o=json.loads(t)
        except:
            try:o=json.loads(repair(t))
            except: continue
        out.append((i,o))
    return out

def walk(n,path="root"):
    if isinstance(n,dict):
        rr=n.get("reviewRating")
        if isinstance(rr,dict) and rr.get("ratingValue") is not None:
            a=n.get("author");name=None;ap=None
            if isinstance(a,dict): name=a.get("name"); ap=path+".author.name"
            elif isinstance(a,list) and a and isinstance(a[0],dict): name=a[0].get("name"); ap=path+".author[0].name"
            return {"critic":name,"rating":rr.get("ratingValue"),"critic_path":ap,"rating_path":path+".reviewRating.ratingValue"}
        for k,v in n.items():
            r=walk(v,path+"."+k)
            if r:return r
    elif isinstance(n,list):
        for idx,v in enumerate(n):
            r=walk(v,f"{path}[{idx}]")
            if r:return r
    return None

def extract(html):
    for idx,obj in jsonlds(html):
        r=walk(obj)
        if r:
            r["jsonld_block"]=idx
            return r
    return None

if len(sys.argv)!=2:
    print("Usage: python extract_jsonld.py data/reviews/file.json"); sys.exit(1)
path=sys.argv[1]
data=json.load(open(path,encoding="utf-8"))
for rev in data["reviews"]:
    url=rev.get("review_url")
    if not url: continue
    print("Processing",url)
    try: html,method=fetch_requests(url)
    except: 
        try: html,method=fetch_playwright(url)
        except:
            rev["fetch_status"]={"status":"blocked"}; continue
    res=extract(html)
    if res:
        if res["critic"] is not None: rev["critic_name"]=res["critic"]
        if res["rating"] is not None: rev["star_rating"]=res["rating"]
        rev["extract_log"]={"jsonld_block":res["jsonld_block"],"critic_path":res["critic_path"],"rating_path":res["rating_path"]}
    rev["fetch_status"]={"status":"ok","method":method}
json.dump(data,open(path,"w",encoding="utf-8"),indent=2,ensure_ascii=False)
