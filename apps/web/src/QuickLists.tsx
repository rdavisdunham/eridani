import {useCallback,useEffect,useLayoutEffect,useRef,useState,type RefObject} from "react";
import {Check,X} from "lucide-react";
import {z} from "zod";
import {api,ApiError,command,commandId,post} from "./api";
import {Dialog} from "./ux";
import {useStructureActions} from "./structure-actions";
import {useEditor} from "./editor-control";
import type {QuickList,Task} from "./types";
import "./capture.css";
function CaptureGuard({busy,dirty,close}:{busy:boolean;dirty:boolean;close:()=>void}){useEditor({kind:"task",mode:"edit",dirty,busy,schema:z.object({}),values:{capture:"Quick list"},patch:async()=>{throw Error("Fill the Quick list form or use Quick capture tools.");},close,discard:close});return null;}
export function parseChecklist(text:string){let section="";return text.split("\n").flatMap(line=>{const value=line.trim();if(!value)return [];if(value.startsWith("# ")){section=value.slice(2).trim();return [];}return [{title:value.replace(/^[-*] (?:\[ \] )?/,""),section}];});}

/** Still on the list: not removed, and not archived away as history. Reorder and the "N done" line count only these. */
export const onList=(item:Task)=>!item.archived&&item.status!=="cancelled";
export const isOpenItem=(item:Task)=>onList(item)&&item.status!=="completed";

/** Pins or unpins a quick list on this person's own Today. Pins are per person, so a viewer can pin too. */
export function pinList(id:string,pinned:boolean){
 return post<{data:{pinned:boolean}}>("/today/pins",{command_id:commandId(),target_id:id,pinned}).then(result=>result.data.pinned);
}

/** A list that just finished, with the command that brings it back: the item checked last, or every item finished with it. */
export type FinishedList={id:string;title:string;undo:()=>Promise<unknown>;
 /** What finished it (its box) held focus and is leaving, so the toast's Undo takes focus. */
 focus?:boolean};
type Command=[tool:string,args:Record<string,unknown>];
type Result=Record<string,unknown>;
type Write={
 /** Shown at once, until the write settles. */
 change?:(list:QuickList)=>QuickList;
 /** The command, built from the newest saved list when its turn comes; null when there is nothing left to do. */
 build:(list:QuickList)=>Command|null;
 /** The command that reverses this one, when its result finished the list. */
 undo?:(result:Result)=>Command|null;
 /** The result is not the list itself: read the list again. */
 reload?:boolean;
 /** A refusal shows under the add field. */
 add?:boolean;
};
// Neither the list nor any item both copies hold went back a revision, so `next` is not an older read.
function fresher(next:QuickList,shown:QuickList|null){
 if(!shown)return true;
 const seen=new Map(shown.items.map(item=>[item.id,item.revision]));
 return next.revision>=shown.revision&&next.items.every(item=>item.revision>=(seen.get(item.id)??0));
}
/** Sends the command; sending it again after a lost connection reuses its command ID. */
function once([tool,args]:Command){const pending=command(tool,args);return ()=>pending.send();}
// Unsaved text in each box's add field, kept for this tab: it survives leaving Today and coming back.
const drafts=new Map<string,string>();

export type QuickListState=ReturnType<typeof useQuickList>;
/**
 * One quick list, read and changed the same way by its dialog and its Today box. Each change shows at once and
 * waits its turn, so it is sent with the revision the change before it produced. After a revision conflict the
 * list is read again and that one change is tried once more. A box passes the list it was given as `snapshot`
 * and reads nothing by itself, and `remember` keeps its add field's text; the dialog reads the list when it opens.
 */
export function useQuickList(id:string,{snapshot,remember=false,onChanged,onFinished}:{snapshot?:QuickList;remember?:boolean;onChanged?:()=>void;onFinished?:(finished:FinishedList)=>void}={}){
 const {run}=useStructureActions();
 const [saved,setSaved]=useState<QuickList|null>(snapshot??null);
 const savedRef=useRef(saved);
 const [writes,setWrites]=useState<Write[]>([]);
 const tail=useRef<Promise<unknown>>(Promise.resolve());
 const [error,setErrorText]=useState(""),[addError,setAddError]=useState(""),errorRef=useRef("");
 const setError=useCallback((message:string)=>{errorRef.current=message;setErrorText(message);},[]);
 const [newItem,setNewItemText]=useState(()=>(remember&&drafts.get(id))||""),newItemRef=useRef(newItem);
 const setNewItem=useCallback((value:string)=>{newItemRef.current=value;if(remember){if(value)drafts.set(id,value);else drafts.delete(id);}setNewItemText(value);},[id,remember]);
 const [draft,setDraft]=useState(false);
 const callbacks=useRef({onChanged,onFinished});callbacks.current={onChanged,onFinished};
 const adopt=useCallback((next:QuickList,force=false)=>{if(!force&&!fresher(next,savedRef.current))return;savedRef.current=next;setSaved(next);},[]);
 const load=useCallback(()=>api<QuickList>("/quick-lists/"+id).then(fresh=>{adopt(fresh,true);return fresh;}),[id,adopt]);
 useEffect(()=>{if(snapshot)adopt(snapshot);},[snapshot,adopt]);
 useEffect(()=>{if(!savedRef.current)void load().catch(e=>setError(e.message));},[load,setError]);
 const write=useCallback((w:Write)=>{
  const fail=w.add?setAddError:setError;
  fail("");
  setWrites(all=>[...all,w]);
  const send=(list:QuickList)=>{const next=w.build(list);return next?run<Result>(...next):Promise.resolve(null);};
  const settled=tail.current.then(async()=>{
   try{
    let result:Result|null;
    try{result=await send(savedRef.current!);}
    catch(e){
     if(!(e instanceof ApiError)||e.code!=="REVISION_CONFLICT")throw e;
     // The list changed elsewhere: read it again and try this one change once more.
     result=await send(await load());
    }
    if(w.reload)await load();
    else if(Array.isArray(result?.items))adopt(result as unknown as QuickList);
    setDraft(false);
    const inverse=result&&w.undo?.(result);
    if(inverse)callbacks.current.onFinished?.({id,title:savedRef.current!.title,undo:once(inverse)});
    if(result)callbacks.current.onChanged?.();
    return result;
   }catch(e){fail((e as Error).message);throw e;}
   finally{setWrites(all=>all.filter(x=>x!==w));}
  });
  tail.current=settled.catch(()=>{});
  return settled;
 },[run,load,adopt,setError]);
 // Checking or removing the last open item finishes the list; undoing that brings back the one item.
 const reopenItem=(item:Task)=>(result:Result):Command|null=>{
  const after=result.list_finished?(result as unknown as QuickList).items?.find(x=>x.id===item.id):undefined;
  return after?["quicklist.item",{list_id:id,expected_revision:result.revision,operation:"edit",item_id:item.id,expected_item_revision:after.revision,completed:false}]:null;
 };
 const onItem=(item:Task,operation:"edit"|"remove",patch:Record<string,unknown>,change:Partial<Task>)=>write({
  change:list=>({...list,items:list.items.map(x=>x.id===item.id?{...x,...change}:x)}),
  build:list=>{const current=list.items.find(x=>x.id===item.id);return current?["quicklist.item",{list_id:id,expected_revision:list.revision,operation,item_id:item.id,expected_item_revision:current.revision,...patch}]:null;},
  undo:reopenItem(item),
 });
 return {
  list:saved&&writes.reduce((shown,w)=>w.change?w.change(shown):shown,saved),
  error,setError,addError,busy:writes.length>0,load,newItem,setNewItem,draft,setDraft,
  /** Waits for the changes already asked for; refuses when the last one was refused. */
  settled:async()=>{await tail.current;if(errorRef.current)throw Error(errorRef.current);},
  check:(item:Task,completed:boolean)=>onItem(item,"edit",{completed},{status:completed?"completed":"open"}),
  rename:(item:Task,title:string)=>onItem(item,"edit",{title},{title}),
  setSection:(item:Task,section:string)=>onItem(item,"edit",{section},{quick_section:section}),
  /** A mistyped item is cancelled, not deleted: it stops counting as open or done. */
  remove:(item:Task)=>onItem(item,"remove",{},{status:"cancelled"}),
  /** Clears the field at once, so the next item can be typed; a refused item comes back to an empty field. */
  add:(text:string,section="")=>{
   const title=text.trim();
   setNewItem("");
   return write({add:true,build:list=>["quicklist.item",{list_id:id,expected_revision:list.revision,operation:"add",title,section}]})
    .catch(e=>{if(!newItemRef.current.trim())setNewItem(title);throw e;});
  },
  /** Reorder sends exactly the items still on the list, as the server requires. */
  move:(item:Task,delta:number)=>write({build:list=>{
   const order=list.items.filter(onList).map(x=>x.id),from=order.indexOf(item.id),to=from+delta;
   if(from<0||to<0||to>=order.length)return null;
   [order[from],order[to]]=[order[to],order[from]];
   return ["quicklist.item",{list_id:id,expected_revision:list.revision,operation:"reorder",order}];
  }}),
  update:(patch:Record<string,unknown>)=>write({reload:true,build:list=>["task.update",{task_id:id,expected_revision:list.revision,...patch}]}),
  promote:(project_id:string|null)=>write({build:list=>["quicklist.promote",{list_id:id,expected_revision:list.revision,project_id}]}),
  /** Finishes the list. With `consent` its unchecked items are completed with it; the undo reopens all of them. */
  finish:(consent:boolean)=>write({
   build:list=>["task.complete",{task_id:id,expected_revision:list.revision,...(consent?{complete_open_items:true}:{})}],
   undo:result=>["task.reopen",{task_id:id,expected_revision:result.revision,item_ids:result.completed_item_ids??[]}],
  }),
  pin:(pinned:boolean)=>pinList(id,pinned).then(value=>{const current=savedRef.current;if(current)adopt({...current,pinned:value},true);return value;},e=>{setError((e as Error).message);throw e;}),
 };
}

/** The checklist without its dialog: the full list, or (`compact`) the rows of a Today box. */
export function QuickListBody({quick,canEdit,compact=false,generation=0,label="",addRef}:{quick:QuickListState;canEdit:boolean;compact?:boolean;generation?:number;label?:string;addRef?:RefObject<HTMLInputElement|null>}){
 return compact?<BoxItems quick={quick} canEdit={canEdit} label={label} addRef={addRef}/>:<FullItems quick={quick} canEdit={canEdit} generation={generation}/>;
}

function FullItems({quick,canEdit,generation}:{quick:QuickListState;canEdit:boolean;generation:number}){
 const [section,setSection]=useState("");
 const list=quick.list!,disabled=quick.busy||!canEdit;
 // Removed items are gone; checked items archived as history follow the others and are not reordered.
 const items=list.items.filter(item=>item.status!=="cancelled"),order=items.filter(onList);
 const save=(value:string,before:string,apply:(value:string)=>Promise<unknown>)=>{if(value!==before)void apply(value).catch(()=>{});else quick.setDraft(false);};
 return <>
  <ol className="quick-checklist">{items.map((item,index)=>{const place=order.indexOf(item);return <li key={item.id+":"+item.revision+":"+generation}><input type="checkbox" aria-label={"Complete "+item.title} checked={item.status==="completed"} disabled={disabled} onChange={e=>void quick.check(item,e.target.checked).catch(()=>{})}/>
   <div className="quick-item-fields"><input aria-label={"Item "+(index+1)} defaultValue={item.title} disabled={disabled} onChange={()=>quick.setDraft(true)} onBlur={e=>save(e.target.value,item.title,value=>quick.rename(item,value))}/><input aria-label={"Section for "+item.title} placeholder="Optional section" defaultValue={item.quick_section??""} disabled={disabled} onChange={()=>quick.setDraft(true)} onBlur={e=>save(e.target.value,item.quick_section??"",value=>quick.setSection(item,value))}/></div>
   {place>=0&&<div className="quick-order">{[-1,1].map(delta=><button key={delta} className="btn-icon" aria-label={(delta<0?"Move up ":"Move down ")+item.title} disabled={disabled||place+delta<0||place+delta>=order.length} onClick={()=>void quick.move(item,delta).catch(()=>{})}>{delta<0?"↑":"↓"}</button>)}</div>}</li>;})}</ol>
  {canEdit&&<form className="quick-list-add" onSubmit={e=>{e.preventDefault();void quick.add(quick.newItem,section).catch(()=>{});}}><input aria-label="New checklist item" placeholder="Add another item…" value={quick.newItem} onChange={e=>quick.setNewItem(e.target.value)}/><input aria-label="New item section" placeholder="Section (optional)" value={section} onChange={e=>setSection(e.target.value)}/><button className="btn" disabled={quick.busy||!quick.newItem.trim()}>Add</button></form>}
  {canEdit&&quick.addError&&<p className="field-error" role="alert">{quick.addError}</p>}
 </>;
}

/** An item's text: plain until tapped or focused, then a field. Enter or leaving it saves; Escape cancels. */
function ItemText({item,canEdit,onRename}:{item:Task;canEdit:boolean;onRename:(title:string)=>void}){
 const [editing,setEditing]=useState(false);
 const text=useRef<HTMLButtonElement>(null),discard=useRef(false),back=useRef(false);
 // After Enter or Escape, focus returns to the text without opening the field again.
 useEffect(()=>{if(!editing&&back.current)text.current?.focus();},[editing]);
 if(!canEdit)return <span className="row-title">{item.title}</span>;
 if(!editing)return <button ref={text} type="button" className="row-title" onClick={()=>setEditing(true)} onFocus={()=>{if(back.current)back.current=false;else setEditing(true);}}>{item.title}</button>;
 return <input className="box-item-input" aria-label={"Edit "+item.title} defaultValue={item.title} maxLength={500} autoFocus
  onKeyDown={e=>{if(e.key!=="Enter"&&e.key!=="Escape")return;e.preventDefault();e.stopPropagation();discard.current=e.key==="Escape";back.current=true;e.currentTarget.blur();}}
  onBlur={e=>{const title=e.currentTarget.value.trim();if(!discard.current&&title&&title!==item.title)onRename(title);discard.current=false;setEditing(false);}}/>;
}

function BoxItems({quick,canEdit,label,addRef}:{quick:QuickListState;canEdit:boolean;label:string;addRef?:RefObject<HTMLInputElement|null>}){
 const list=quick.list!;
 const open=list.items.filter(isOpenItem),done=list.items.filter(item=>onList(item)&&item.status==="completed");
 const checks=useRef(new Map<string,HTMLButtonElement>()),field=useRef<HTMLInputElement|null>(null),focusNext=useRef<string|null>(null);
 // When a checked or removed item leaves the open items, focus goes to the next one's check, or to the add field.
 useLayoutEffect(()=>{const target=focusNext.current;if(!target)return;focusNext.current=null;(target==="add"?field.current:checks.current.get(target))?.focus();});
 const leave=(item:Task,control:HTMLElement)=>{if(document.activeElement===control)focusNext.current=open[open.findIndex(x=>x.id===item.id)+1]?.id??"add";};
 const setField=(element:HTMLInputElement|null)=>{field.current=element;if(addRef)addRef.current=element;};
 return <>
  {quick.error&&<p className="today-error" role="alert">{quick.error}</p>}
  {open.length?<ul className="today-rows box-open">{open.map(item=><li key={item.id} className="row today-row box-item">
   {canEdit&&<button type="button" className="check" aria-label={"Check off "+item.title} ref={element=>{if(element)checks.current.set(item.id,element);else checks.current.delete(item.id);}}
    onClick={e=>{leave(item,e.currentTarget);void quick.check(item,true).catch(()=>{});}}><Check aria-hidden="true"/></button>}
   <div className="row-main"><ItemText item={item} canEdit={canEdit} onRename={title=>void quick.rename(item,title).catch(()=>{})}/>{item.quick_section&&<span className="box-item-section">{item.quick_section}</span>}</div>
   {canEdit&&<div className="row-actions"><button type="button" className="btn-icon box-remove" aria-label={"Remove "+item.title} onClick={e=>{leave(item,e.currentTarget);void quick.remove(item).catch(()=>{});}}><X aria-hidden="true"/></button></div>}
  </li>)}</ul>
   :<p className="box-state">{done.length?"All done":canEdit?"Add your first item.":"No items yet."}</p>}
  {canEdit&&<form className="box-add" onSubmit={e=>{e.preventDefault();if(quick.newItem.trim())void quick.add(quick.newItem).catch(()=>{});}}>
   <input ref={setField} aria-label={"Add to "+label} placeholder="Add an item…" maxLength={500} value={quick.newItem} onChange={e=>quick.setNewItem(e.target.value)}/>
   <button className="btn btn-soft btn-sm" disabled={!quick.newItem.trim()}>Add</button>
  </form>}
  {canEdit&&quick.addError&&<p className="today-error" role="alert">{quick.addError}</p>}
  {!!done.length&&<details className="box-done"><summary>{done.length} done</summary><ul className="today-rows">{done.map(item=><li key={item.id} className="row today-row box-item done">
   {canEdit&&<button type="button" className="check done" aria-pressed="true" aria-label={"Uncheck "+item.title}
    onClick={e=>{if(document.activeElement===e.currentTarget)focusNext.current=item.id;void quick.check(item,false).catch(()=>{});}}><Check aria-hidden="true"/></button>}
   <div className="row-main"><span className="row-title">{item.title}</span></div>
  </li>)}</ul></details>}
 </>;
}

export function QuickCapture({onCreated}:{onCreated:(task:Task)=>void}){
 const [open,setOpen]=useState(false),[title,setTitle]=useState(""),[text,setText]=useState(""),[due,setDue]=useState(""),[clock,setClock]=useState(""),[pin,setPin]=useState<boolean|null>(null);const {run,busy,error}=useStructureActions();
 // A new list is pinned to Today unless it gets a deadline; ticking or clearing the box decides either way.
 const pinned=pin??!due;
 return <><button className="btn btn-soft" onClick={()=>setOpen(true)}>+ Quick list</button>{open&&<Dialog aria-label="New Quick list" className="dialog-card capture-card" onEscape={()=>{if(!busy)setOpen(false);}}><CaptureGuard busy={busy} dirty={!!(title||text)} close={()=>setOpen(false)}/><h2>One list. No setup.</h2><p>A checklist for what you’re doing now. Use # for optional section headings.</p><form onSubmit={e=>{e.preventDefault();void run<Task>("quicklist.create",{title,items:parseChecklist(text),due_date:due||null,due_time:due&&clock?clock:null,pinned}).then(task=>{setOpen(false);setTitle("");setText("");setDue("");setClock("");setPin(null);onCreated(task);}).catch(()=>{});}}>
 <label className="field">List title<input aria-label="List title" required maxLength={500} value={title} onChange={e=>setTitle(e.target.value)}/></label>
 <label className="field">Checklist<textarea aria-label="Checklist" rows={7} value={text} onChange={e=>setText(e.target.value)} placeholder={"# Hayes\nPack food\n# Moped\nGather tools"}/></label><div className="capture-options"><label className="field">Optional deadline<input type="date" value={due} onChange={e=>setDue(e.target.value)}/></label><label className="field">Optional time<input aria-label="Deadline time" type="time" disabled={!due} value={clock} onChange={e=>setClock(e.target.value)}/></label><label><input type="checkbox" checked={pinned} onChange={e=>setPin(e.target.checked)}/> Pin to Today</label></div>
 <p className="footnote">No alerts unless you turn them on. Unfinished items stay when the deadline passes.</p>{error&&<p role="alert">{error}</p>}<button className="btn btn-primary" disabled={busy||!title.trim()||parseChecklist(text).length>100}>Create list</button><button type="button" className="btn" disabled={busy} onClick={()=>setOpen(false)}>Cancel</button></form></Dialog>}</>;
}
export function QuickListDetail({id,onClose,onChanged,canEdit=true,refresh=0}:{refresh?:number;id:string;onClose:()=>void;onChanged:()=>void;canEdit?:boolean}){
 const quick=useQuickList(id,{onChanged});
 const {list,error,setError,draft,setDraft,newItem}=quick;
 const [project,setProject]=useState(""),[reloadKey,setReloadKey]=useState(0),[projects,setProjects]=useState<{id:string;name:string}[]>([]),[pinning,setPinning]=useState(false);
 const busy=quick.busy||pinning;const card=useRef<HTMLDivElement>(null);
 useEffect(()=>{void api<{items:{id:string;name:string}[]}>("/projects").then(d=>setProjects(d.items)).catch(()=>{});},[id]);
 const seen=useRef(refresh);
 useEffect(()=>{if(seen.current===refresh)return;seen.current=refresh;if(!busy&&!draft&&!newItem.trim()&&!error)void quick.load().catch(e=>setError(e.message));},[refresh]);
 const finish=async()=>{if(card.current?.contains(document.activeElement))(document.activeElement as HTMLElement)?.blur();await quick.settled();if(newItem.trim())throw Error("Add or clear the unsaved checklist item before leaving.");};
 const close=()=>void finish().then(onClose).catch(e=>setError(e.message));
 useEditor({kind:"task",record_id:id,mode:"detail",auto_save:true,dirty:draft||!!newItem.trim(),busy:!list,schema:z.object({}),values:list?{title:list.title,items:list.items}: {},beforeLeave:finish,patch:async()=>{throw Error("Use Quick capture tools to edit this checklist.");},close:onClose});
 const metadata=(patch:Record<string,unknown>)=>void quick.update(patch).catch(()=>{});
 // Counted from the items shown, so a check counts at once; the same counts the server reads.
 const done=list?list.items.filter(x=>x.status==="completed").length:0,total=list?list.items.filter(x=>x.status!=="cancelled").length:0;
 return <Dialog aria-label="Quick list" className="dialog-card capture-card" onEscape={close}><div ref={card}><button className="btn-icon capture-close" aria-label="Close Quick list" onClick={close}>×</button>{!list?<p>{error||"Loading list…"}</p>:<>
 <label className="field">List title<input aria-label="Quick list title" defaultValue={list.title} key={list.title+reloadKey} disabled={!canEdit||busy} onChange={()=>setDraft(true)} onBlur={e=>{if(e.target.value!==list.title)metadata({title:e.target.value});else setDraft(false);}}/></label><p role="status">{done} of {total} done · {total-done} remaining</p>
 {error&&<div role="alert"><p>{error} Unsaved text is kept.</p><button className="btn" onClick={()=>void quick.load().then(()=>{setError("");setDraft(false);quick.setNewItem("");setReloadKey(k=>k+1);})}>Reload saved list</button></div>}
 <div className="capture-options"><label className="field">Deadline<input aria-label="List deadline" type="date" disabled={!canEdit||busy} value={list.due_date??""} onChange={e=>metadata({due_date:e.target.value||null})}/></label><label className="field">Time<input aria-label="List deadline time" type="time" disabled={!canEdit||busy||!list.due_date} value={list.due_time?.slice(0,5)??""} onChange={e=>metadata({due_time:e.target.value||null})}/></label><label><input type="checkbox" disabled={pinning} checked={!!list.pinned} onChange={e=>{setPinning(true);void quick.pin(e.target.checked).then(()=>onChanged(),()=>{}).finally(()=>setPinning(false));}}/> Pin to Today</label><label><input type="checkbox" disabled={!canEdit||busy||!list.due_date} checked={list.deadline_alert==="on"} onChange={e=>metadata({deadline_alert:e.target.checked?"on":"off"})}/> Deadline alert</label></div>
 <p className="footnote">Date-only alerts appear in the daily summary. Use task scheduling with Dani for a timed reminder.</p>
 <QuickListBody quick={quick} canEdit={canEdit} generation={reloadKey}/>
 {canEdit&&<details><summary>Use as normal tasks</summary><p>The same items become ordinary subtasks. Completion, IDs and history stay intact; nothing is copied.</p><select aria-label="Project for promoted list" value={project} onChange={e=>setProject(e.target.value)}><option value="">No project needed</option>{projects.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><button className="btn" disabled={busy||draft||!!newItem.trim()} onClick={()=>void quick.promote(project||null).then(onClose).catch(()=>{})}>Promote to tasks</button></details>}
 </>}</div></Dialog>;
}
