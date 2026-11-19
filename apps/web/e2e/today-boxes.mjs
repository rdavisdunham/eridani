import {chromium,expect} from "@playwright/test";
import {mkdirSync} from "node:fs";
const base=process.env.JARVIS_PLANNER_TEST_URL;
const browser=await chromium.launch();const page=await browser.newPage({viewport:{width:390,height:844}});const errors=[];page.on("pageerror",e=>errors.push(e.message));
async function request(path,body){return page.evaluate(async({path,body})=>{const boot=await(await fetch("/api/v1/bootstrap")).json();const r=await fetch("/api/v1"+path,{method:body?"POST":"GET",headers:{"Content-Type":"application/json","X-CSRF-Token":boot.csrf},...(body?{body:JSON.stringify(body)}:{})});const data=await r.json();if(!r.ok)throw Error(JSON.stringify(data));return data;},{path,body});}
const cmd=async(tool,args)=>(await request("/commands",{command_id:crypto.randomUUID(),tool,arguments:args})).data;
const ui=async(name,args)=>{const r=await request("/__test_ui",{name,arguments:args});if(r.status!=="displayed")throw Error(JSON.stringify(r));};
try{
 await page.goto(base);await page.getByLabel("Pairing code").fill("planner-fixture");await page.locator(".login-card button.primary").click();await expect(page.getByRole("region",{name:"Today",exact:true})).toBeVisible();
 const zone=(await request("/bootstrap")).preferences.timezone;const today=new Intl.DateTimeFormat("en-CA",{timeZone:zone}).format(new Date());
 const rev=(await request("/structure")).revision;
 const project=await cmd("record.create",{type_id:"project",title:"Launch acceptance",schema_revision:rev});
 await cmd("task.create",{title:"Ship launch notes",parent_task_id:project.task_id,due_date:today});
 await cmd("task.create",{title:"Plan the retro",parent_task_id:project.task_id});
 // Pin the project from its header in Organize; the header then offers to unpin it.
 await ui("ui_records",{layout:"browse",parent_id:project.id});
 const browse=page.getByRole("region",{name:"Browse organization"});await expect(browse.getByRole("heading",{name:project.title})).toBeVisible();
 await browse.getByRole("button",{name:"Pin to Today",exact:true}).click();await expect(browse.getByRole("button",{name:"Unpin from Today",exact:true})).toBeVisible();
 // On Today the project has its own box with its task for today, which Due and overdue lists too; undated work stays out.
 await ui("ui_workspace",{view:"today"});
 const box=page.getByRole("region",{name:project.title,exact:true});await expect(box).toBeVisible();
 await expect(box.getByRole("button",{name:"Complete Ship launch notes",exact:true})).toBeVisible();await expect(box.getByText("Plan the retro",{exact:true})).toHaveCount(0);
 const due=page.getByRole("region",{name:"Due and overdue",exact:true});await expect(due.getByRole("button",{name:"Complete Ship launch notes",exact:true})).toBeVisible();
 // Adding in the box files the task in the project, planned for today.
 await box.getByLabel("Add to "+project.title,{exact:true}).fill("Write the changelog");await box.getByRole("button",{name:"Add",exact:true}).click();
 await expect(box.getByRole("button",{name:"Complete Write the changelog",exact:true})).toBeVisible();
 const added=(await request("/tasks?limit=200")).items.find(t=>t.title==="Write the changelog");
 expect([added.parent_task_id,added.planned_date]).toEqual([project.task_id,today]);
 // Finishing the project's task from Due and overdue takes it out of the box too.
 await due.getByRole("button",{name:"Complete Ship launch notes",exact:true}).click();await expect(box.getByRole("button",{name:"Complete Ship launch notes",exact:true})).toHaveCount(0);
 for(const width of [390,1280]){await page.setViewportSize({width,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();mkdirSync("../../artifacts/today-boxes",{recursive:true});await box.screenshot({path:`../../artifacts/today-boxes/project-box-${width}.png`});}
 // The box's title opens the project; unpinning it there takes the box off Today.
 await box.getByRole("button",{name:project.title,exact:true}).click();await expect(browse.getByRole("heading",{name:project.title})).toBeVisible();
 await browse.getByRole("button",{name:"Unpin from Today",exact:true}).click();await expect(browse.getByRole("button",{name:"Pin to Today",exact:true})).toBeVisible();
 await ui("ui_workspace",{view:"today"});await expect(page.getByRole("region",{name:"Due and overdue",exact:true})).toBeVisible();await expect(box).toHaveCount(0);
 if(errors.length)throw Error(errors.join("\n"));console.log("Today boxes browser passed: a project pinned in Organize gets a box on Today with its tasks for today, adds there file in the project for today, a finish in Due clears the box, and unpinning in Organize removes it.");
}finally{await browser.close();}
