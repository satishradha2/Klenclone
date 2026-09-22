const form=document.querySelector('#login-form');
const error=document.querySelector('#error');
const button=form.querySelector('button');
const buttonLabel=document.querySelector('#sign-in-label');
const transition=document.querySelector('#login-transition');
const transitionTitle=document.querySelector('#transition-title');
const transitionDetail=document.querySelector('#transition-detail');
const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)');
let submitting=false;

const delay=milliseconds=>new Promise(resolve=>setTimeout(resolve,reducedMotion.matches?0:milliseconds));
function showTransition(title,detail,phase='loading'){
  transitionTitle.textContent=title;
  transitionDetail.textContent=detail;
  transition.dataset.phase=phase;
  transition.classList.remove('is-dismissed');
  transition.setAttribute('aria-hidden','false');
}
function hideTransition(){
  transition.classList.add('is-dismissed');
  transition.setAttribute('aria-hidden','true');
  delete document.body.dataset.loginState;
}
function restoreForm(){
  submitting=false;
  button.disabled=false;
  button.classList.remove('is-loading');
  buttonLabel.textContent='Sign in to workspace';
  form.classList.remove('auth-error');
  void form.offsetWidth;
  form.classList.add('auth-error');
}

addEventListener('load',async()=>{await delay(520);hideTransition()},{once:true});
form.addEventListener('animationend',event=>{if(event.animationName==='form-reject')form.classList.remove('auth-error')});
form.addEventListener('submit',async event=>{
  event.preventDefault();
  if(submitting)return;
  submitting=true;
  const started=performance.now();
  error.textContent='';
  button.disabled=true;
  button.classList.add('is-loading');
  buttonLabel.textContent='Authenticating…';
  document.body.dataset.loginState='authenticating';
  showTransition('Authenticating access','Verifying your independent ERP credentials');
  try{
    const response=await fetch('/api/v1/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.username.value,password:form.password.value})});
    const data=await response.json();
    if(!response.ok)throw Error(data.detail||'Sign-in failed');
    const remaining=Math.max(0,520-(performance.now()-started));
    await delay(remaining);
    buttonLabel.textContent='Opening workspace…';
    document.body.dataset.loginState='leaving';
    showTransition('Preparing your workspace','Loading navigation, permissions and operational context','success');
    await delay(420);
    location.replace('/?arrival=1');
  }catch(reason){
    error.textContent=reason instanceof Error?reason.message:'Sign-in failed';
    hideTransition();
    restoreForm();
    form.password.focus();
  }
});
