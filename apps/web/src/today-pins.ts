import { api, commandId, post } from "./api";

/** One box kept on this person's Today: a quick list (its task ID) or a project (its home record's ID). */
export type TodayPin = { kind: "quick_list" | "project"; target_id: string; pinned_at: string };

/** Pins or unpins a box on this person's own Today. Pins are per person, so a viewer can pin too. */
export function pinToToday(id: string, pinned: boolean) {
  return post<{ data: { pinned: boolean } }>("/today/pins", { command_id: commandId(), target_id: id, pinned })
    .then(result => result.data.pinned);
}

/** This person's pins, including targets with no box today, such as a finished project. */
export function readPins() {
  return api<{ pins: TodayPin[] }>("/today/pins").then(result => result.pins);
}
