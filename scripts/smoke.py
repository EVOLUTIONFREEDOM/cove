import httpx

s = httpx.Client(base_url="http://127.0.0.1:8787", follow_redirects=True, timeout=20)
r = s.get("/")
print("GET /", r.status_code, "Cove" in r.text)
r = s.get("/signup")
print("GET /signup", r.status_code)
r = s.post("/signup", data={"email": "cove-demo@example.com", "password": "password1"})
print("signup", r.status_code, str(r.url), "data-page" in r.text)
r = s.get("/api/me")
print("me", r.status_code, r.text[:240])
for path in ("/home", "/trade", "/options", "/calendar", "/dividends", "/activity", "/alerts", "/account"):
    r = s.get(path)
    print(path, r.status_code, r.text.find('id="view"') >= 0)
