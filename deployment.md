# Deployment: Render + Cloudflare

This app is deployed on Render and served publicly at:

```text
https://wfsf.gopicreations.com
```

Cloudflare owns DNS for `gopicreations.com`. Render hosts the app.

## Target Setup

```text
Browser
  -> Cloudflare zone: gopicreations.com
  -> DNS: wfsf.gopicreations.com
  -> Render service: <your-service>.onrender.com
  -> FastAPI app
```

Use Cloudflare for:

- proxied DNS
- DDoS protection
- bot protection
- WAF rules
- rate limiting
- static asset caching

Use Render for:

- app hosting
- TLS certificate for the custom domain
- automatic HTTPS redirect

## 1. Add Custom Domain in Render

1. Open Render Dashboard.
2. Select the WFSF web service.
3. Go to `Settings` -> `Custom Domains`.
4. Add:

```text
wfsf.gopicreations.com
```

5. Render will show a target like:

```text
<your-service>.onrender.com
```

Keep this value for the Cloudflare DNS record.

## 2. Create DNS Record in Cloudflare

In Cloudflare:

1. Open the `gopicreations.com` zone.
2. Go to `DNS` -> `Records`.
3. Add this record:

```text
Type: CNAME
Name: wfsf
Target: <your-service>.onrender.com
Proxy status: DNS only
TTL: Auto
```

Use `DNS only` first so Render can verify the domain and issue its certificate.

Do not add an `AAAA` record for this hostname.

## 3. Verify Domain in Render

1. Return to Render.
2. Go to the service's `Custom Domains` section.
3. Click `Verify` for:

```text
wfsf.gopicreations.com
```

4. Wait until Render shows the domain and certificate as valid.
5. Open:

```text
https://wfsf.gopicreations.com
```

Confirm the app loads.

## 4. Enable Cloudflare Proxy

After Render verification succeeds:

1. Go back to Cloudflare DNS.
2. Edit the `wfsf` CNAME record.
3. Change:

```text
Proxy status: Proxied
```

The record should now be orange-clouded.

## 5. Configure Cloudflare SSL

Cloudflare:

```text
SSL/TLS -> Overview
Encryption mode: Full
```

Render recommends `Full` for Cloudflare DNS setup.

After the site works reliably, `Full (strict)` can be tested. If SSL errors appear, return to `Full`.

Also enable:

```text
SSL/TLS -> Edge Certificates -> Always Use HTTPS: On
SSL/TLS -> Edge Certificates -> Automatic HTTPS Rewrites: On
```

Do not enable HSTS until the deployment has been verified end-to-end.

## 6. Disable Render Default Subdomain

This prevents users from bypassing Cloudflare through:

```text
<your-service>.onrender.com
```

In Render:

1. Open the WFSF service.
2. Go to `Settings` -> `Custom Domains`.
3. Set:

```text
Render Subdomain: Disabled
```

After this, direct requests to the Render subdomain should return `404` and should not reach the app.

## 7. Set Render Environment Variables

In Render:

```text
APP_BASE_URL=https://wfsf.gopicreations.com
COOKIE_SECURE=true
DEV_OTP_LOG=false
SESSION_SECRET=<long-random-production-secret>
RESEND_API_KEY=<real-resend-key>
RESEND_FROM=<verified-sender>
TURNSTILE_SITE_KEY=<cloudflare-turnstile-site-key>
TURNSTILE_SECRET_KEY=<cloudflare-turnstile-secret-key>
```

Then redeploy the service.

## 8. Configure Turnstile

In Cloudflare:

1. Go to `Turnstile`.
2. Create or edit the widget.
3. Add this hostname:

```text
wfsf.gopicreations.com
```

4. Copy the site key and secret key into Render env vars.

## 9. Enable Bot Protection

Cloudflare:

```text
Security -> Bots
Bot Fight Mode: On
```

On Pro or Business plans, use `Super Bot Fight Mode` instead.

## 10. Add WAF Rules

Cloudflare:

```text
Security -> WAF -> Custom rules
```

### Challenge Login

```text
Name: Challenge WFSF login
Expression:
(http.host eq "wfsf.gopicreations.com" and http.request.uri.path in {"/login" "/login/request" "/login/verify"})
Action: Managed Challenge
```

### Challenge High-Risk Writes

```text
Name: Challenge WFSF high-risk writes
Expression:
(http.host eq "wfsf.gopicreations.com"
 and http.request.method eq "POST"
 and http.request.uri.path in {"/login/request" "/login/verify" "/admin/users/invite"})
Action: Managed Challenge
```

## 11. Add Rate Limiting Rules

Cloudflare:

```text
Security -> WAF -> Rate limiting rules
```

### OTP Request Limit

```text
Name: Limit WFSF OTP requests
Expression:
(http.host eq "wfsf.gopicreations.com" and http.request.uri.path eq "/login/request")
Characteristics: IP
Period: 60 seconds
Requests: 5
Action: Managed Challenge
Duration: 10 minutes
```

### OTP Verify Limit

```text
Name: Limit WFSF OTP verification
Expression:
(http.host eq "wfsf.gopicreations.com" and http.request.uri.path eq "/login/verify")
Characteristics: IP
Period: 60 seconds
Requests: 10
Action: Managed Challenge
Duration: 10 minutes
```

### General POST Limit

```text
Name: Limit WFSF writes
Expression:
(http.host eq "wfsf.gopicreations.com" and http.request.method eq "POST")
Characteristics: IP
Period: 60 seconds
Requests: 60
Action: Managed Challenge
Duration: 5 minutes
```

If the Cloudflare plan allows only one rate limit rule, keep `Limit WFSF OTP requests`.

## 12. Add Cache Rule for Static Assets

Cloudflare:

```text
Rules -> Cache Rules -> Create rule
```

```text
Name: Cache WFSF static assets
Expression:
(http.host eq "wfsf.gopicreations.com" and starts_with(http.request.uri.path, "/static/"))
Cache eligibility: Eligible for cache
Edge TTL: 1 month
Browser TTL: Respect origin
```

Do not cache HTML routes:

```text
/login
/browse
/my-schedule
/day-of
/admin
```

## 13. Optional: Render Inbound IP Rules

Only available for Render web services on Scale or Enterprise plans.

If available:

1. Render service -> `Networking`.
2. Open `Inbound IP Restrictions`.
3. Allow Cloudflare IPv4 CIDR ranges.
4. Remove:

```text
0.0.0.0/0
```

Skip this on lower Render plans.

## 14. Verification Checklist

Run these checks after setup:

```bash
curl -I https://wfsf.gopicreations.com/healthz
curl -I https://wfsf.gopicreations.com/login
curl -I https://<your-service>.onrender.com/healthz
```

Expected:

- `wfsf.gopicreations.com` returns through Cloudflare.
- `/login` loads and Turnstile appears.
- direct `onrender.com` URL returns `404` after Render subdomain is disabled.
- session cookie is marked `Secure`.
- Cloudflare Security Events show challenges/rate-limit activity when rules trigger.

## Cost Notes

```text
Render built-in DDoS protection: included
Cloudflare Free plan: $0/month
Cloudflare Pro: about $20/month annually or $25/month monthly
Render extra custom domains: may cost $0.25/month beyond included plan quota
Render inbound IP rules for web services: Scale or Enterprise only
```

Start with Cloudflare Free. Upgrade only if more WAF/rate-limit rules or better bot controls are needed.
