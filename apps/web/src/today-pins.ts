import { api, commandId, post } from "./api";
import type { TodayBoxData } from "./types";

/** One of this person's pins: a quick list (its task ID) or a project (its home record's ID). It has a box only while its target is open. */
export type TodayPin = { kind: TodayBoxData["kind"]; target_id: string; pinned_at: string };

/** Pins or unpins a box on this person's own Today. Pins are per person, so a viewer can pin too. */
export function pinToToday(id: string, pinned: boolean) {
  return post<{ data: { pinned: boolean } }>("/today/pins", { command_id: commandId(), target_id: id, pinned })
    .then(result => result.data.pinned);
}

/** This person's pins, including targets with no box today, such as a finished project. */
export function readPins() {
  return api<{ pins: TodayPin[] }>("/today/pins").then(result => result.pins);
}
