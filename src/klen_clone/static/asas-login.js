const form=document.querySelector('#login-form'),error=document.querySelector('#error'),button=form.querySelector('button');
async function existing(){const r=await fetch('/api/v1/auth/session');const d=await r.json();if(d.authenticated)location.replace('/')}
form.addEventListener('submit',async e=>{e.preventDefault();error.textContent='';button.disabled=true;button.textContent='Signing in…';try{const r=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.username.value,password:form.password.value})});const d=await r.json();if(!r.ok)throw Error(d.detail||'Sign-in failed');location.replace('/')}catch(e){error.textContent=e.message;button.disabled=false;button.textContent='Sign in'}});
existing().catch(()=>{});
