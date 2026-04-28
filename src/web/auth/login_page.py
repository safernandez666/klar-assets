"""Standalone login page HTML, served by the middleware and by GET /auth/login."""
from __future__ import annotations

from src.web.config import _OKTA_OIDC_ENABLED


def login_page() -> str:
    """Render the dark-themed Klar login page (with optional Okta SSO button)."""
    okta_section = ""
    if _OKTA_OIDC_ENABLED:
        okta_section = """
      <div style="margin-top:20px;text-align:center">
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
          <div style="flex:1;height:1px;background:rgba(255,255,255,0.08)"></div>
          <span style="font-size:11px;color:var(--gray-4);text-transform:uppercase;letter-spacing:1px">or</span>
          <div style="flex:1;height:1px;background:rgba(255,255,255,0.08)"></div>
        </div>
        <a href="/auth/okta" style="display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:12px;background:transparent;border:1.5px solid rgba(255,255,255,0.15);border-radius:10px;color:var(--white);font-size:13px;font-weight:500;text-decoration:none;transition:all 0.2s;font-family:inherit"
           onmouseover="this.style.borderColor='rgba(255,255,255,0.3)';this.style.background='rgba(255,255,255,0.03)'"
           onmouseout="this.style.borderColor='rgba(255,255,255,0.15)';this.style.background='transparent'">
          <svg width="32" height="32" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg"><circle cx="32" cy="32" r="30" fill="#007DC1"/><circle cx="32" cy="32" r="14" fill="#fff"/></svg>
          Sign in with Okta
        </a>
      </div>"""
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in</title>
<link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,400;0,500;0,700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root{--black:#0f0f0f;--white:#fff;--gray-1:#f7f7f5;--gray-2:#ebebea;--gray-3:#c4c4c3;--gray-4:#8a8a89;--gray-5:#555;--red:#c0392b;--green:#10b981}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%}
body{font-family:'DM Sans',system-ui,sans-serif;background:var(--black);color:var(--white);overflow:hidden}

/* Animated grid background */
.grid-bg{position:fixed;inset:0;z-index:0;
  background-image:
    linear-gradient(rgba(255,255,255,0.03) 1px,transparent 1px),
    linear-gradient(90deg,rgba(255,255,255,0.03) 1px,transparent 1px);
  background-size:48px 48px;
  animation:gridShift 20s linear infinite}
@keyframes gridShift{from{transform:translate(0,0)}to{transform:translate(48px,48px)}}

/* Scan line effect */
.scanline{position:fixed;inset:0;z-index:1;pointer-events:none;
  background:repeating-linear-gradient(0deg,transparent,transparent 2px,rgba(255,255,255,0.008) 2px,rgba(255,255,255,0.008) 4px)}

/* Floating orb */
.orb{position:fixed;width:600px;height:600px;border-radius:50%;z-index:0;filter:blur(120px);opacity:0.07;
  background:radial-gradient(circle,var(--green),transparent 70%);
  top:-200px;right:-200px;animation:orbFloat 15s ease-in-out infinite alternate}
@keyframes orbFloat{0%{transform:translate(0,0)}100%{transform:translate(-80px,80px)}}

/* Layout */
.wrapper{position:relative;z-index:2;display:flex;height:100vh}
.left{flex:1;display:flex;flex-direction:column;justify-content:center;padding:0 8vw}
.right{width:480px;display:flex;align-items:center;justify-content:center;padding:40px}

/* Left panel */
.brand{font-size:clamp(42px,5vw,64px);font-weight:700;letter-spacing:-2px;line-height:1;margin-bottom:12px;
  animation:fadeUp 0.8s ease both}
.tagline{font-size:15px;color:var(--gray-4);font-weight:400;line-height:1.6;max-width:340px;
  animation:fadeUp 0.8s ease 0.1s both}
.tagline strong{color:var(--gray-3);font-weight:500}
.status-bar{position:absolute;bottom:40px;left:8vw;display:flex;gap:24px;
  animation:fadeUp 0.8s ease 0.3s both}
.status-item{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--gray-4);
  display:flex;align-items:center;gap:6px}
.dot{width:6px;height:6px;border-radius:50%;background:var(--green);
  box-shadow:0 0 8px var(--green);animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}

/* Right panel — card */
.card{width:100%;max-width:360px;background:rgba(255,255,255,0.03);
  border:1px solid rgba(255,255,255,0.08);border-radius:20px;padding:44px 36px;
  backdrop-filter:blur(20px);animation:fadeUp 0.6s ease 0.15s both}
.card-title{font-size:14px;font-weight:500;color:var(--gray-3);margin-bottom:32px;
  letter-spacing:0.5px;text-transform:uppercase}
.field{margin-bottom:22px}
.field label{display:block;font-size:11px;font-weight:500;color:var(--gray-4);
  text-transform:uppercase;letter-spacing:1.2px;margin-bottom:8px}
.field input{width:100%;padding:12px 16px;background:rgba(255,255,255,0.04);
  border:1px solid rgba(255,255,255,0.1);border-radius:10px;color:var(--white);
  font-size:14px;font-family:'DM Sans',sans-serif;outline:none;transition:all 0.25s}
.field input:focus{border-color:rgba(255,255,255,0.3);background:rgba(255,255,255,0.06);
  box-shadow:0 0 0 3px rgba(255,255,255,0.04)}
.field input::placeholder{color:var(--gray-4)}
.btn{width:100%;padding:14px;background:var(--white);color:var(--black);border:none;
  border-radius:10px;font-size:14px;font-weight:600;font-family:inherit;cursor:pointer;
  transition:all 0.2s;letter-spacing:0.2px;margin-top:4px}
.btn:hover{background:var(--gray-2);transform:translateY(-1px);box-shadow:0 4px 20px rgba(255,255,255,0.1)}
.btn:active{transform:translateY(0)}
.btn:disabled{opacity:0.5;cursor:not-allowed;transform:none}
.error-msg{color:var(--red);font-size:12px;margin-bottom:16px;padding:10px 14px;
  background:rgba(192,57,43,0.08);border:1px solid rgba(192,57,43,0.15);border-radius:8px;
  display:none;animation:shake 0.4s ease}
@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-6px)}40%,80%{transform:translateX(6px)}}
.footer{text-align:center;margin-top:24px;font-size:11px;color:var(--gray-4)}

@keyframes fadeUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}

/* Responsive */
@media(max-width:900px){
  .wrapper{flex-direction:column}
  .left{flex:none;padding:40px 32px 20px;text-align:center;align-items:center}
  .left .tagline{margin:0 auto}
  .right{width:100%;flex:1;padding:20px 32px 40px}
  .status-bar{position:static;justify-content:center;margin-top:20px}
}
</style>
</head>
<body>
<div class="grid-bg"></div>
<div class="scanline"></div>
<div class="orb"></div>

<div class="wrapper">
  <div class="left">
    <div class="brand">Klar</div>
    <div class="tagline">
      <strong>Device Normalizer</strong><br>
      Fleet visibility across JumpCloud, CrowdStrike &amp; Okta — unified in one secure dashboard.
    </div>
    <div class="status-bar">
      <div class="status-item"><span class="dot"></span> System operational</div>
      <div class="status-item" id="ver">loading...</div>
    </div>
  </div>

  <div class="right">
    <div class="card">
      <div class="card-title">Sign in to continue</div>
      <div class="error-msg" id="err"></div>
      <form id="form" autocomplete="on">
        <div class="field">
          <label for="user">Username</label>
          <input type="text" id="user" name="username" autocomplete="username" placeholder="admin" required>
        </div>
        <div class="field">
          <label for="pass">Password</label>
          <input type="password" id="pass" name="password" autocomplete="current-password" placeholder="&bull;&bull;&bull;&bull;&bull;&bull;&bull;&bull;" required>
        </div>
        <button class="btn" type="submit" id="btn">Sign in</button>
      </form>
      {okta_section}
      <div class="footer">IT Security Team</div>
    </div>
  </div>
</div>

<script>
document.getElementById('form').addEventListener('submit',async(e)=>{
  e.preventDefault();
  const err=document.getElementById('err'),btn=document.getElementById('btn');
  err.style.display='none';
  btn.disabled=true;btn.textContent='Authenticating...';
  try{
    const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({username:document.getElementById('user').value,
        password:document.getElementById('pass').value})});
    if(r.ok){btn.textContent='Redirecting...';location.href='/'}
    else{const d=await r.json();err.textContent=d.error||'Authentication failed';
      err.style.display='block';btn.disabled=false;btn.textContent='Sign in';
      document.getElementById('pass').value='';document.getElementById('pass').focus()}
  }catch(ex){err.textContent='Connection error';err.style.display='block';
    btn.disabled=false;btn.textContent='Sign in'}
});
fetch('/api/version').then(r=>r.json()).then(d=>{
  const v=d.version==='dev'?'dev':d.version.slice(0,7);
  document.getElementById('ver').textContent=v;
}).catch(()=>{document.getElementById('ver').textContent='v1.0'});
</script>
</body>
</html>""".replace("{okta_section}", okta_section)
