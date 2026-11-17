import {chromium,expect} from "@playwright/test";
import {mkdirSync} from "node:fs";
const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on("pageerror",e=>errors.push(e.message));
const base=process.env.JARVIS_PLANNER_TEST_URL;
async function request(path,body){return page.evaluate(async({path,body})=>{const boot=await(await fetch("/api/v1/bootstrap")).json();const r=await fetch("/api/v1"+path,{method:body?"POST":"GET",headers:{"Content-Type":"application/json","X-CSRF-Token":boot.csrf},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(JSON.stringify(data));return data;},{path,body});}
try{
 await page.goto(base);await page.getByLabel("Pairing code").fill("planner-fixture");await page.locator(".login-card button.primary").click();await expect(page.getByRole("region",{name:"Today",exact:true})).toBeVisible();
 await page.waitForTimeout(500);await request("/__test_reviews",{});
 // The nav entry carries the count once the list is read again (the page reload re-reads it).
 await page.reload();
 const nav=page.getByRole("button",{name:"Needs you",exact:true});await expect(nav).toBeVisible();await expect(nav).toContainText("2");
 await nav.click();
 const section=page.getByRole("region",{name:"Needs you",exact:true});
 await expect(section.locator(".needs-you-summary")).toHaveText("2 things are waiting for you.");
 await expect(section.locator(".needs-you-card")).toHaveCount(2);
 const field=section.locator(".needs-you-card").filter({hasText:"Does Client mean a company or a person?"});
 await expect(field.locator("h3")).toHaveText("Answer a question");await expect(field.getByRole("button",{name:"Accept"})).toHaveCount(0);
 expect((await request("/needs-you")).total).toBe(2);
 for(const width of [390,892,1440]){
  await page.setViewportSize({width,height:1000});await page.waitForTimeout(400);await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  mkdirSync("../../artifacts/needs-you",{recursive:true});await page.screenshot({path:"../../artifacts/needs-you/list-"+width+".png",fullPage:true});
 }
 await page.setViewportSize({width:1440,height:1000});
 // Open goes where the item is decided; the deep link comes back to the list.
 await field.getByRole("button",{name:"Open"}).click();await expect(page.getByRole("region",{name:"Questions",exact:true})).toBeVisible();
 await page.goto(base+"/?view=needs");await expect(page.getByRole("region",{name:"Needs you",exact:true}).locator(".needs-you-card")).toHaveCount(2);
 if(errors.length)throw Error(errors.join("\n"));
 console.log("Needs you acceptance passed: nav count, cards with decision and Open, deep link, phone/fold/desktop layouts.");
}finally{await browser.close();}
