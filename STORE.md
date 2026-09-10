# Get Cove into the App Store and Google Play

Cove’s native shells live in `mobile/`. They are Capacitor apps that open your hosted Cove website (the FastAPI app). **This computer is Windows**, so Android can be built here. **Apple does not allow compiling an iPhone app on Windows.** You do **not** need to buy a Mac, and you do **not** need Flutter. Rent a Mac in the cloud (Codemagic) and install the result on your iPhone with **TestFlight**.

Bundle ID / application id: `com.cove.trade`  
App Store Connect Apple ID: `6810722839`

---

## Public TestFlight link (outside testers)

A public link (`https://testflight.apple.com/join/…`) only works after **all** of these are true:

1. The trading desk is on a **stable HTTPS host** (not this PC’s Cloudflare tunnel).
2. Codemagic env `COVE_SERVER_URL` is that HTTPS URL.
3. Test information is filled in App Store Connect.
4. A **non–internal-only** IPA is uploaded and **Beta App Review** approves it.
5. That build is on an **external** group, then you turn on **Public Link**.

Do the steps in this order. Do not start Codemagic until step 3 is saved.

### 1. Host the desk (Fly.io)

This PC is not a server. If the tunnel stops, every public-link tester sees a dead app, and Apple rejects Beta Review.

1. Open [https://fly.io/app/sign-up](https://fly.io/app/sign-up) and create a free account (GitHub login is fine).
2. Add a payment card if Fly asks (needed for an always-on machine).
3. On this PC, PowerShell:

```powershell
iwr https://fly.io/install.ps1 -useb | iex
cd C:\Users\User\Desktop\cove
fly auth login
fly apps create alpaca-cove-desk
fly volumes create cove_data --region lhr --size 1 -y
fly secrets set APP_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" APP_URL=https://alpaca-cove-desk.fly.dev
fly deploy
```

4. In a browser open `https://alpaca-cove-desk.fly.dev/health` — you should see `{"ok":true}`.
5. Open `/privacy` and `/terms` on that same host. Apple will load those URLs.

If the app name `alpaca-cove-desk` is taken, create another name and use that hostname everywhere below.

### 2. Test information (required before a public link)

1. Open [Test information](https://appstoreconnect.apple.com/apps/6810722839/testflight/test-info).
2. Fill **every** required field, then Save:

- **Beta App Description:** Alpaca Cove is an iPhone desk for people who already have Alpaca. We are not a broker. Paper trading uses keys that start with PK.
- **Feedback Email:** `evolutioninvestments79@gmail.com`
- **First Name:** your legal first name
- **Last Name:** your legal last name
- **Phone:** a number Apple can call
- **Email:** `steven@evolutionfreedomltd.co.uk` (or the Active Apple ID email)
- **Privacy Policy URL:** `https://alpaca-cove-desk.fly.dev/privacy` (your real host)
- **What to Test:** paste `mobile/testflight-notes.txt` (replace YOUR-HOSTED-DESK with the Fly URL)

Without this page complete, Codemagic post-processing fails and the public link never appears.

### 3. Codemagic variable

1. Open Codemagic → app **cove** → **Environment variables**.
2. Add `COVE_SERVER_URL`
3. Value: `https://alpaca-cove-desk.fly.dev` (no trailing slash)
4. Group: **`code-signing`**
5. You can leave Secret off so you can see it.
6. Save.

### 4. Start the iPhone build

1. Codemagic → **cove** → branch **main**.
2. **Start new build** → workflow **Cove iPhone (TestFlight)**.
3. Wait until the IPA uploads. Post-processing then submits it to group **`testers 1`** for **Beta App Review**.
4. Watch [TestFlight iOS](https://appstoreconnect.apple.com/apps/6810722839/testflight/ios). Status should become **Waiting for Review**, then **Ready to Test**. That can take a few hours or a day.

The workflow **refuses** to build if `COVE_SERVER_URL` is missing or still a trycloudflare tunnel.

### 5. Turn on the public link

1. Open [TestFlight iOS](https://appstoreconnect.apple.com/apps/6810722839/testflight/ios).
2. Left sidebar, under **External Testing**, click **`testers 1`**.
3. Confirm the new **1.0.1** build is listed (not an old build marked Internal).
4. Under testers, click **Create Public Link** (or **Enable Public Link**).
5. Choose **Open to Anyone**.
6. Optional: set a tester limit (for example 100).
7. Confirm. Copy `https://testflight.apple.com/join/…`

Testers: install **TestFlight** from the App Store, tap your link, then **Accept** → **Install**.

If the group still says **No builds available**, the IPA is Internal Only or Beta Review has not approved it yet. Do not share the link until the build on that group is **Testing**.

---

## No Mac, still an iPhone app

Flutter would not help. Every iOS binary is produced by Apple’s compiler, which only runs on macOS. Cove already has the Xcode project. A cloud Mac builds it.

### Fastest path: Codemagic → TestFlight → your iPhone

1. Push this repo to GitHub (public or private).
2. Create the app in [App Store Connect](https://appstoreconnect.apple.com) with bundle ID `com.cove.trade`.
3. In App Store Connect → Users and Access → Integrations → App Store Connect API, create a key with **App Manager**. Download the `.p8` once.
4. Sign up at [codemagic.io](https://codemagic.io), add the GitHub repo, scan for `codemagic.yaml`.
5. Team integrations → Developer Portal → add that API key. Name it exactly `Cove` (that name is what `codemagic.yaml` expects).
6. Create a signing key on this Windows PC (once). In PowerShell, from the Cove folder:

```powershell
ssh-keygen -t rsa -b 2048 -m PEM -f .\ios_distribution_private_key -q -N ([string]::Empty)
Get-Content .\ios_distribution_private_key
```

Copy the whole PEM block (`BEGIN RSA PRIVATE KEY` through `END RSA PRIVATE KEY`). Do not commit this file.

7. In Codemagic → the Cove app → Environment variables: name `CERTIFICATE_PRIVATE_KEY`, paste the PEM, group name **`code-signing`**, mark it **Secret**.
8. Start the workflow **Cove iPhone (TestFlight)**. The first run creates the Apple App ID, distribution certificate, and App Store profile if they do not exist yet.
9. When it finishes, open **TestFlight** on your iPhone (same Apple ID as the developer account, or add your phone as an internal tester) and install Cove.

You never open Xcode. You never buy a Mac. Codemagic bills for Mac minutes after the free allowance.

`codemagic.yaml` is already in the repo root. GitHub Actions (`.github/workflows/ios.yml`) is a backup if you prefer GitHub’s Mac runners; Codemagic is easier for signing.

A Safari “Add to Home Screen” shortcut is **not** an App Store app. Use TestFlight if you want the real iPhone app.

---

## 0. You must host Cove on HTTPS first

Store apps cannot talk to `127.0.0.1` on a reviewer’s phone.

1. Deploy the FastAPI app to a host with a real domain and TLS (Fly.io, Railway, Render, a VPS + Caddy, etc.).
2. Set `APP_URL=https://your-domain` in that host’s `.env`.
3. Put the same URL in `mobile/www/server.json`:

```json
{ "url": "https://your-domain" }
```

4. From `mobile/` run:

```powershell
$env:PATH = "$PWD\..\tools\node-v22.19.0-win-x64;$env:PATH"
npx cap sync
```

Privacy and terms URLs reviewers will open:

- `https://your-domain/privacy`
- `https://your-domain/terms`

---

## 1. Accounts and money

| Store | Account | Cost (typical) |
| --- | --- | --- |
| Apple | [Apple Developer Program](https://developer.apple.com/programs/) enrolled as an individual or company | $99 / year |
| Google | [Google Play Console](https://play.google.com/console) | $25 one-time |

Company enrollment at Apple can take days (D-U-N-S). Start that while you finish the product.

**Subscriptions inside the iOS app:** Apple requires In-App Purchase for digital subscriptions sold in the app (guideline 3.1.1). Stripe checkout is hidden on iOS native for that reason. To charge inside the iPhone app you must create an Auto-Renewable Subscription in App Store Connect (product id e.g. `cove_pro_monthly`) and wire StoreKit. US-only external web checkout is possible with extra Apple entitlements after Epic v. Apple — have counsel decide. The website can still bill with Stripe.

**Google Play:** digital subscriptions sold in the Play app generally need [Play Billing](https://developer.android.com/google/play/billing). You can keep the Android Stripe buttons for a web-style product, but Play review may ask you to switch to Play Billing if they classify Cove Pro as an in-app digital good.

**How you get paid on Play:** create a payments profile in Play Console (legal name, address, tax form, bank account). People pay Google. Google keeps its service fee (often about 15% on subscriptions; one-time can be 15–30%). The rest is paid to your bank on Google’s monthly payout calendar, after a short hold, once you are above their minimum. This is separate from Stripe website payouts. Create Play products that match the app: `cove_pro_monthly` at $9.99 and `cove_pro_lifetime` at $199.

Cove is an **Alpaca interface**, not a broker. Say that in the listing, in the app, and in review notes. Alpaca remains the broker of record. You will still need to satisfy each store’s finance / trading app questions.

---

## 2. Android — Google Play

### Build a signed AAB (what Play wants)

On this Windows machine, after JDK 21 and Android SDK exist (see `tools/`):

```powershell
cd $HOME\Desktop\cove\mobile\android
$env:JAVA_HOME = "...\tools\jdk-21.0.12.1+1"   # folder that contains bin\java.exe
$env:ANDROID_HOME = "...\tools\android-sdk"
.\gradlew.bat bundleRelease
```

The Play upload file is:

`mobile/android/app/build/outputs/bundle/release/app-release.aab`

Create an upload keystore once:

```powershell
keytool -genkey -v -keystore cove-upload.jks -keyalg RSA -keysize 2048 -validity 10000 -alias cove
```

Point Gradle at it with `android/key.properties` (do not commit passwords):

```
storeFile=cove-upload.jks
storePassword=...
keyAlias=cove
keyPassword=...
```

### Play Console listing

1. Create app → **App name: Cove**
2. Default language, app or game: **App**
3. Category: **Finance**
4. Free, with in-app products if you use Play Billing
5. Short description (~80 chars): `Alpaca trading desk: stocks, options, P&L and dividend calendars.`
6. Full description: interface-only, Alpaca custody, paper vs live, options risk, not investment advice
7. Graphics: 512×512 icon (use `mobile/assets/icon.png` resized), 1080×1920 phone screenshots (at least 2), optional 7" / 10" tablet
8. Privacy policy URL: `https://your-domain/privacy`
9. Data safety form: collect email, crash logs; encrypted Alpaca tokens on your server; no sale of data
10. Content rating questionnaire (IARC)
11. Target audience: 18+
12. News app / COVID / government: no
13. Finance: declare investing / trading functionality; you are not the broker
14. **Account deletion**: Play requires an in-app path and a web path to delete the account. Add that before you ship.

### Testing track

Upload the AAB to **Internal testing**, add your Gmail, install from the Play opt-in link, then promote to Closed → Production. First review often takes a few days.

Production needs a **closed test with 12 testers for 14 days** if your developer account is new (Play policy for new personal accounts). Start that immediately.

---

## 3. iOS — App Store (no local Mac)

Use the **No Mac** section above to get a build onto your iPhone via TestFlight. Submitting that same build for App Store review is a toggle in Codemagic (`submit_to_app_store: true`) after screenshots and listings are filled in App Store Connect.

If you ever use a borrowed or cloud desktop Mac instead:

```bash
cd cove/mobile
npm install
npx cap sync ios
npx cap open ios
```

In Xcode: Signing & Capabilities → your Team, bundle `com.cove.trade`, Archive → App Store Connect.

### App Store Connect

1. Apps → New → iOS, bundle `com.cove.trade`
2. Privacy policy URL
3. Category: Finance
4. Age rating questionnaire
5. Screenshots: 6.7" iPhone required (and iPad if you tick iPad)
6. Review notes: “Cove is a client for the user’s own Alpaca account. We do not custody assets. Paper keys start with PK. Live trading requires Alpaca approval of any OAuth app.”
7. Demo account: create one on production with paper keys already linked so the reviewer can tap Trade without signing up at Alpaca
8. If you sell a subscription in the iOS app: Features → Subscriptions → create `cove_pro_monthly`, 7–14 day free trial to match the website, App Store server notifications to your webhook

App Review regularly rejects trading apps that:

- look like they are the broker
- have a broken demo login
- charge with Stripe inside the iOS binary
- lack a privacy policy
- allow live trading with no risk disclosures

---

## 4. What this repo already built

| Path | What it is |
| --- | --- |
| `mobile/android/` | Android Studio / Gradle project |
| `mobile/ios/` | Xcode project (open on a Mac) |
| `mobile/www/` | Packaged loader; points at `server.json` |
| `mobile/assets/icon.png` | 1024×1024 store icon |
| `app/templates/privacy.html` | `/privacy` |
| `app/templates/terms.html` | `/terms` |

Phone layout: bottom tab bar under 900px width, safe-area padding, Stripe hidden on native iOS.

---

## 5. Local phone testing (before stores)

1. Run Cove: `.\.venv\Scripts\python.exe run.py` (port 8787)
2. Put your PC’s LAN IP in `mobile/www/server.json`, e.g. `http://192.168.1.20:8787`
3. Android emulator uses `http://10.0.2.2:8787` (already the default)
4. `npx cap sync` then open Android Studio (`npx cap open android`) or Xcode on a Mac
5. Windows firewall must allow inbound 8787

---

## 6. Honest limits

- iOS binaries cannot be compiled on this Windows PC. Use Codemagic (see the No Mac section) so a rented Mac builds the existing Xcode project. Flutter is not required and would not remove that Apple rule.
- Google Play and Apple will still review you as a **finance app**. Budget extra review time and a paper-trading demo user.
- Have a lawyer review `/privacy` and `/terms` before you submit. The pages in this repo are a starting draft.
- Alpaca Connect live trading for other users still needs Alpaca’s written approval. The mobile app does not change that.
