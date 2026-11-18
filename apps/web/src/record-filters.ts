import type {CustomRecord} from "./structure-types";

/**
 * Row rules for the Tasks page and Organization lists. Kept apart from Structure.tsx so the
 * rules that decide whether a record shows up are unit-tested.
 */

/** Case-insensitive substring of the title, notes, type name or field values. */
export function literalMatch(r:Pick<CustomRecord,"title"|"body"|"type_name"|"values">,query:string){
  const needle=query.trim().toLowerCase();
  if(!needle)return true;
  return [r.title,r.body,r.type_name,JSON.stringify(r.values)].join(" ").toLowerCase().includes(needle);
}

/**
 * A search keeps a row that the server ranked (word, meaning or learned-alias match) or that
 * contains the query literally. The literal match shows at once, before any request returns,
 * and is never dropped when the server's ranking arrives ("ignore", "time-var", "gnore").
 */
export function matchesQuery(r:Pick<CustomRecord,"id"|"title"|"body"|"type_name"|"values">,query:string,ranked:Map<string,number>|null){
  if(!query.trim())return true;
  return !!ranked?.has(r.id)||literalMatch(r,query);
}

/** Ranked rows first in server order, then literal-only matches in their existing order. */
export function rankOrder(ranked:Map<string,number>){
  return (a:{id:string},b:{id:string})=>(ranked.get(a.id)??ranked.size)-(ranked.get(b.id)??ranked.size);
}

/**
 * Main home: the home itself as parent, any ancestor, or a task's legacy project. A project
 * created through the legacy project API keeps its tasks' project_id even when a record's saved
 * home drifted elsewhere.
 */
export function inHome(r:Pick<CustomRecord,"parent_id"|"home"|"project_id">,home:string){
  if(!home)return true;
  return r.parent_id===home||r.home.some(p=>p.id===home)||r.project_id===home;
}

export type TaskTabScope="today"|"week"|"inbox"|"all"|string;

/** Whether a row belongs to a task tab: Inbox has no home; Today/Week are planned or due by then. */
export function inTab(r:Pick<CustomRecord,"parent_id">,tab:TaskTabScope,dates:string[],today:string,weekEnd:string){
  if(tab==="inbox")return !r.parent_id;
  if(tab==="today"||tab==="week"){const until=tab==="today"?today:weekEnd;return dates.filter(Boolean).some(d=>d<=until);}
  return true;
}

/** The task IDs of the quick lists among these rows that are still open: not finished and not archived. */
export function openQuickLists(rows:Pick<CustomRecord,"is_quick_list"|"task_id"|"archived"|"status_meaning">[]){
  return new Set(rows.filter(r=>r.is_quick_list&&r.task_id&&!r.archived&&!["completed","cancelled"].includes(r.status_meaning??"")).map(r=>r.task_id!));
}

/**
 * A quick list's items stay inside their list on the Tasks page. A search finds them, and the Today tab lists one
 * while its list is open, as Today's "Due and overdue" does; the tab's date rule then keeps only items whose own
 * due or do date has come.
 */
export function quickItemShown(r:Pick<CustomRecord,"quick_list_parent_id">,openLists:Set<string>,todayTab:boolean,searching:boolean){
  return !r.quick_list_parent_id||searching||(todayTab&&openLists.has(r.quick_list_parent_id));
}
