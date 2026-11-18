// @vitest-environment jsdom
import {act} from "react";
import {createRoot,type Root} from "react-dom/client";
import {afterEach,beforeEach,describe,it,expect,vi} from "vitest";
import {parseChecklist,QuickCapture,QuickListDetail} from "./QuickLists";
import {renderToStaticMarkup} from "react-dom/server";
import {BrandMark} from "./ux";
import type {QuickList,Task} from "./types";
describe("Quick capture",()=>{
 it("keeps sections as display labels without inventing items",()=>{expect(parseChecklist("# Hayes\nFood\n\n# Work\nLaptop")).toEqual([{title:"Food",section:"Hayes"},{title:"Laptop",section:"Work"}]);});
 it("accepts plain lines and pasted empty checkboxes",()=>{expect(parseChecklist("- [ ] Keys\n* Wallet\nPassport").map(i=>i.title)).toEqual(["Keys","Wallet","Passport"]);});
 it("does not infer completion from user text",()=>{expect(parseChecklist("- [x] Check with Alex")[0].title).toBe("[x] Check with Alex");});
 it("renders an accessible vector mark",()=>{const html=renderToStaticMarkup(<BrandMark title="Eridani"/>);expect(html).toContain('aria-label="Eridani"');expect(html).toContain('viewBox="0 0 48 48"');});
});

(globalThis as {IS_REACT_ACT_ENVIRONMENT?:boolean}).IS_REACT_ACT_ENVIRONMENT=true;
const item=(id:string,title:string,extra:Partial<Task>={})=>({id,title,status:"open",revision:1,archived:false,quick_section:"",parent_task_id:"L",...extra}) as Task;
const quickList=(items:Task[],extra:Partial<QuickList>={})=>({id:"L",title:"Groceries",status:"open",revision:5,archived:false,is_quick_list:true,due_date:null,due_time:null,planned_date:null,items,
 done:items.filter(i=>i.status==="completed").length,total:items.filter(i=>i.status!=="cancelled").length,...extra}) as QuickList;
type Call={method:string;url:string;body:{tool?:string;arguments?:Record<string,unknown>;[key:string]:unknown}};
type Reply={status:number;body:unknown};
let host:HTMLDivElement,root:Root,calls:Call[],serve:(call:Call)=>Reply|Promise<Reply>;
const ok=(body:unknown)=>({status:200,body}),done=(data:unknown)=>ok({command_id:"c",status:"succeeded",data});
beforeEach(()=>{host=document.createElement("div");document.body.append(host);root=createRoot(host);calls=[];
 vi.stubGlobal("fetch",async(url:string,init:RequestInit={})=>{const call={method:init.method??"GET",url,body:init.body?JSON.parse(String(init.body)):{}};calls.push(call);
  const reply=call.url==="/api/v1/projects"?ok({items:[]}):await serve(call);return {ok:reply.status<400,status:reply.status,json:async()=>reply.body,headers:new Headers()};});});
afterEach(()=>{act(()=>root.unmount());host.remove();vi.unstubAllGlobals();});
const flush=()=>act(async()=>{for(let i=0;i<5;i++)await new Promise(r=>setTimeout(r,0));});
const commands=()=>calls.filter(c=>c.url==="/api/v1/commands").map(c=>({tool:c.body.tool,arguments:c.body.arguments}));
const labelled=(text:string)=>[...document.querySelectorAll("label")].find(l=>l.textContent?.trim().startsWith(text))!.querySelector("input")!;
function type(element:HTMLInputElement,value:string){Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,"value")!.set!.call(element,value);element.dispatchEvent(new Event("input",{bubbles:true}));}

describe("the full list",()=>{
 it("reorders only the items still on the list: not removed ones, not archived history",async()=>{
  const list=quickList([item("a","Milk"),item("b","Eggs",{status:"completed"}),item("c","Typo",{status:"cancelled"}),item("d","Butter",{status:"completed",archived:true,archive_reason:"automatic"})]);
  serve=call=>call.method==="GET"?ok(list):done(quickList([list.items[1],list.items[0],list.items[2],list.items[3]],{revision:6}));
  await act(async()=>root.render(<QuickListDetail id="L" onClose={()=>{}} onChanged={()=>{}}/>));
  await flush();
  expect(document.querySelector('[aria-label="Move down Typo"]')).toBeNull();
  await act(async()=>document.querySelector<HTMLButtonElement>('[aria-label="Move down Milk"]')!.click());
  await flush();
  expect(commands()).toEqual([{tool:"quicklist.item",arguments:{list_id:"L",expected_revision:5,operation:"reorder",order:["b","a"]}}]);
 });
 it("stays open with the typed item when an add sent just before closing is refused",async()=>{
  const onClose=vi.fn();let answer!:(reply:Reply)=>void;
  serve=call=>call.method==="GET"?ok(quickList([item("a","Milk")])):new Promise<Reply>(resolve=>{answer=resolve;});
  await act(async()=>root.render(<QuickListDetail id="L" onClose={onClose} onChanged={()=>{}}/>));
  await flush();
  const field=document.querySelector<HTMLInputElement>('[aria-label="New checklist item"]')!;
  await act(async()=>type(field,"Eggs"));
  await act(async()=>field.form!.requestSubmit());
  expect(field.value).toBe("");
  await act(async()=>document.querySelector<HTMLButtonElement>('[aria-label="Close Quick list"]')!.click());
  await act(async()=>answer({status:409,body:{error:{code:"LIST_FULL",message:"Quick lists hold up to 100 items."}}}));
  await flush();
  expect(onClose).not.toHaveBeenCalled();
  expect(document.querySelector<HTMLInputElement>('[aria-label="New checklist item"]')!.value).toBe("Eggs");
  expect([...document.querySelectorAll('[role="alert"]')].map(e=>e.textContent)).toContain("Add or clear the unsaved checklist item before leaving. Unsaved text is kept.Reload saved list");
 });
 it("pins and unpins the list for this person, a viewer too, without touching its do date",async()=>{
  const onChanged=vi.fn();
  serve=call=>call.method==="GET"?ok(quickList([item("a","Milk")],{pinned:true})):done({kind:"quick_list",target_id:"L",pinned:call.body.pinned});
  await act(async()=>root.render(<QuickListDetail id="L" canEdit={false} onClose={()=>{}} onChanged={onChanged}/>));
  await flush();
  const pin=labelled("Pin to Today");
  expect(pin.checked).toBe(true);
  expect(pin.disabled).toBe(false);
  await act(async()=>pin.click());
  await flush();
  expect(calls.filter(c=>c.method==="POST").map(c=>[c.url,c.body.target_id,c.body.pinned])).toEqual([["/api/v1/today/pins","L",false]]);
  expect(labelled("Pin to Today").checked).toBe(false);
  expect(onChanged).toHaveBeenCalledTimes(1);
 });
});

describe("a new Quick list from Tasks",()=>{
 it("is pinned to Today unless it gets a deadline",async()=>{
  serve=()=>done(quickList([],{id:"N",title:"Errands",pinned:true}));
  const onCreated=vi.fn();
  await act(async()=>root.render(<QuickCapture onCreated={onCreated}/>));
  await act(async()=>[...document.querySelectorAll("button")].find(b=>b.textContent==="+ Quick list")!.click());
  expect(labelled("Pin to Today").checked).toBe(true);
  await act(async()=>type(labelled("Optional deadline"),"2026-11-20"));
  expect(labelled("Pin to Today").checked).toBe(false);
  await act(async()=>type(labelled("Optional deadline"),""));
  expect(labelled("Pin to Today").checked).toBe(true);
  await act(async()=>type(document.querySelector<HTMLInputElement>('[aria-label="List title"]')!,"Errands"));
  await act(async()=>document.querySelector<HTMLFormElement>("form")!.requestSubmit());
  await flush();
  expect(commands()).toEqual([{tool:"quicklist.create",arguments:{title:"Errands",items:[],due_date:null,due_time:null,pinned:true}}]);
  expect(onCreated).toHaveBeenCalledTimes(1);
 });
});
