/* Optional, explicitly mutating local mock checkout/payment check. Fictional records remain. */
import assert from 'node:assert/strict';

export async function checkBuyerPayment({evaluate,send,until,screenshot,base}){
  assert.equal(base,'http://127.0.0.1:8031');
  const baseline=await evaluate(`(async()=>{
    const health=await (await fetch('/health')).json(),ready=await (await fetch('/ready')).json();
    if(health.run_mode!=='mock'||ready.auth!=='disabled')throw Error('Local mock demo required');
    return await (await fetch('/v1/commerce/state')).json();
  })()`);
  let orderId;
  try{
    await evaluate(`document.getElementById('email').value='payment-ui-'+crypto.randomUUID()+'@example.test';document.getElementById('password').value='Fictional-payment-test-42';document.getElementById('register').click()`);
    await until(()=>evaluate("!!user && !document.getElementById('signed-in').hidden && !!document.querySelector('#products button:not([disabled])')"),'buyer signed in and ready');
    await evaluate(`document.querySelector('#products button:not([disabled])').click()`);
    await until(()=>evaluate('cartItems.length===1'),'buyer added product');
    await evaluate(`{
      const form=document.getElementById('address-form');
      for(const [key,value] of Object.entries({recipient:'Payment Demo Buyer',line1:'123 Example Street',city:'Seattle',state:'WA',postal_code:'98101'}))form.elements.namedItem(key).value=value;
      form.querySelector('button').click();
    }`);
    await until(()=>evaluate("!!document.getElementById('address').value"),'demo address saved');
    await evaluate("document.getElementById('checkout').click()");
    orderId=await until(()=>evaluate("document.querySelector('[data-pay-order]')?.dataset.payOrder"),'buyer pending order and enabled payment');
    assert(await evaluate("!document.querySelector('[data-pay-order]').disabled"));
    await screenshot('buyer-payment-pending');
    await evaluate("document.querySelector('[data-pay-order]').click()");
    await until(()=>evaluate(`document.querySelector('[data-order-id="${orderId}"] .badge')?.textContent==='paid'`),'buyer simulated payment success');
    assert(await evaluate(`!document.querySelector('[data-order-id="${orderId}"] [data-pay-order]')`));
    const paid=await evaluate(`(async()=>{
      const replay=await api('/my/orders/${orderId}/pay',{});
      const seller=await (await fetch('/v1/commerce/orders/${orderId}')).json();
      return {status:replay.status,sellerStatus:seller.status,events:seller.display.payment.events.length};
    })()`);
    assert.deepEqual(paid,{status:'paid',sellerStatus:'paid',events:1});
    await screenshot('buyer-payment-paid');
    await send('Page.reload');
    await until(()=>evaluate(`document.querySelector('[data-order-id="${orderId}"] .badge')?.textContent==='paid'`),'payment persisted after reload');
    await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
    assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'buyer mobile overflow');
    await evaluate("document.getElementById('orders').scrollIntoView()");
    await screenshot('buyer-payment-mobile');
  }finally{
    // Keep the audit trail; release reserved inventory or refund the test payment.
    const cleanup=await evaluate(`(async()=>{
      const orders=await api('/my/orders');
      for(const order of orders){
        if(order.status==='pending')await api('/my/orders/'+order.id+'/cancel',{});
        else if(order.status==='paid'){
          const refund=await api('/my/orders/'+order.id+'/refund',{reason:'Browser simulated payment verification; restore test inventory'});
          const response=await fetch('/v1/commerce/refunds/'+refund.id+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({approve:true,note:'Local browser test cleanup; no real funds'})});
          if(!response.ok)throw Error('Test refund cleanup failed');
        }
      }
      return await (await fetch('/v1/commerce/state')).json();
    })()`);
    assert.deepEqual(cleanup.products,baseline.products,'existing products and inventory preserved');
    assert.deepEqual(cleanup.orders.filter(o=>baseline.orders.some(b=>b.id===o.id)),baseline.orders,'all prior orders preserved');
  }
  return {status:'passed',order_id:orderId,final_status:'refunded',prior_orders_preserved:baseline.orders.length,inventory_restored:true,
    checks:'Real buyer UI register/address/cart/checkout/pay/reload/mobile, seller sees paid, replay has one payment event; fictional order refunded afterward'};
}
