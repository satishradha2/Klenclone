/* In-context operational party requests; no source-system writes. */
let partyCountryCatalogCache;
function loadPartyCountryCatalog(){
  if(!partyCountryCatalogCache)partyCountryCatalogCache=fetch('/api/v1/master-data/country-catalog')
    .then(async response=>{const body=await response.json();if(!response.ok)throw Error(body.detail||'Country catalog unavailable');return body})
    .catch(error=>{partyCountryCatalogCache=null;throw error});
  return partyCountryCatalogCache;
}
function openPartyQuickCreate(kind,afterRequest=()=>{}){
  if(!['customer','supplier'].includes(kind)||!currentPermissions.has(`${kind}.manage`))return;
  const dialog=document.createElement('dialog');dialog.className='party-quick-dialog';
  dialog.innerHTML=`<form class="party-quick-form"><header><div><small>GOVERNED MASTER SETUP</small><h3>Request new ${kind}</h3></div><button type="button" class="party-quick-close" aria-label="Close">×</button></header><p>Create the master without losing your current document. A different authorized user must approve it. GCC and international parties can be recorded, but cross-border transactions remain held until tax, FX and trade controls are configured.</p><div class="party-quick-grid"><label>Code *<input name="party_code" maxlength="80" pattern="[A-Za-z0-9][A-Za-z0-9._-]{1,79}" required autocomplete="off"></label><label>Business name *<input name="legal_or_business_name" maxlength="500" required autocomplete="off"></label><label>Country *<select name="country_code" required disabled><option value="">Loading countries…</option></select></label><label>Preferred currency *<select name="preferred_currency_code" required disabled><option value="">Loading currencies…</option></select></label><p class="party-quick-wide party-market-note" role="status"></p><label>Contact<input name="contact_name" maxlength="300"></label><label>Email<input name="email" type="email" maxlength="320"></label><label>Mobile<input name="mobile" maxlength="120"></label><label>Tax/VAT registration number<input name="tax_number" maxlength="120" autocomplete="off"></label><label class="party-tax-detail" hidden>Registration type<select name="tax_registration_type"><option value="">Select type</option><option value="vat">VAT</option><option value="gst">GST</option><option value="other">Other</option></select></label><label class="party-tax-detail" hidden>Issuing country<select name="tax_country_code"><option value="">Select country</option></select></label><label class="party-quick-wide">Registered address<textarea name="address" maxlength="2000" rows="2"></textarea></label></div><p class="party-quick-result" role="alert" aria-live="assertive"></p><footer><button type="button" class="party-quick-cancel">Cancel</button><button class="primary" type="submit" disabled>Submit for approval</button></footer></form>`;
  document.body.append(dialog);
  const form=dialog.querySelector('form'),country=form.elements.country_code,currency=form.elements.preferred_currency_code,
    taxNumber=form.elements.tax_number,taxType=form.elements.tax_registration_type,taxCountry=form.elements.tax_country_code,
    result=dialog.querySelector('.party-quick-result'),submit=form.querySelector('[type="submit"]');
  const close=()=>dialog.close();
  dialog.querySelectorAll('.party-quick-close,.party-quick-cancel').forEach(button=>button.onclick=close);
  dialog.addEventListener('close',()=>dialog.remove(),{once:true});
  const refreshTax=()=>{const hasTax=Boolean(taxNumber.value.trim());form.querySelectorAll('.party-tax-detail').forEach(label=>label.hidden=!hasTax);taxType.required=hasTax;taxCountry.required=hasTax;if(hasTax&&!taxCountry.value)taxCountry.value=country.value;if(!hasTax){taxType.value='';taxCountry.value=''}};
  taxNumber.oninput=refreshTax;
  form.onsubmit=async event=>{
    event.preventDefault();
    const payload={party_kind:kind,...Object.fromEntries(new FormData(form).entries())};
    for(const key of ['contact_name','email','mobile','tax_number','tax_registration_type','tax_country_code','address'])payload[key]=(payload[key]||'').trim()||null;
    submit.disabled=true;result.textContent='';
    try{
      const response=await fetch('/api/v1/master-data/party-requests',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
      const body=await response.json().catch(()=>({}));
      if(!response.ok)throw Error(Array.isArray(body.detail)?body.detail.map(x=>x.msg).join('; '):body.detail||'Unable to submit master request');
      close();afterRequest(body);
    }catch(error){result.textContent=error.message;submit.disabled=false}
  };
  dialog.showModal();form.elements.party_code.focus();
  loadPartyCountryCatalog().then(catalog=>{
    if(!dialog.isConnected)return;
    const putOptions=(select,rows,key,label)=>{select.replaceChildren(new Option('Select '+label,'',true,false));for(const row of rows)select.add(new Option(`${row.name} (${row[key]})`,row[key]));select.disabled=false};
    putOptions(country,catalog.countries,'code','country');
    putOptions(taxCountry,catalog.countries,'code','country');
    putOptions(currency,catalog.currencies,'code','currency');
    country.value='AE';currency.value='AED';submit.disabled=false;
    let suggestedCurrency='AED',previousCountry='AE';
    country.onchange=()=>{
      const selected=catalog.countries.find(row=>row.code===country.value),next=selected?.currency_suggestion||'';
      if(!currency.value||currency.value===suggestedCurrency)currency.value=next;
      suggestedCurrency=next;
      if(!taxCountry.value||taxCountry.value===previousCountry)taxCountry.value=country.value;
      previousCountry=country.value;
      const scope=selected?.market_scope;
      dialog.querySelector('.party-market-note').textContent=scope==='uae'?'UAE party · domestic staging workflow':scope==='gcc'?'GCC party · cross-border transactions held pending tax and FX controls':scope==='international'?'International party · cross-border transactions held pending tax, FX and trade controls':'';
    };
    country.onchange();refreshTax();
  }).catch(error=>{if(dialog.isConnected)result.textContent=error.message});
}
