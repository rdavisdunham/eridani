import { useCallback, useEffect, useRef, useState } from "react";

// ---- Undo toast -------------------------------------------------------------------------
export type UndoToastState = {
  message: string; undo?: () => Promise<unknown>;
  /** Undo takes focus, because what had focus is leaving the page (a finished list's box). */
  focus?: boolean;
} | null;
/**
 * A six-second status toast with an optional Undo button. It stays while focus is on it, and its six seconds start
 * again once focus moves on.
 */
export function useUndoToast(onUndone?: () => Promise<void> | void, undoneMessage = "Undone.") {
  const [toast, setToast] = useState<UndoToastState>(null), [busy, setBusy] = useState(false), [held, setHeld] = useState(false);
  const undoButton = useRef<HTMLButtonElement>(null);
  const show = useCallback((next: UndoToastState) => { setHeld(false); setToast(next); }, []);
  useEffect(() => { if (!toast || held) return; const timer = setTimeout(() => setToast(null), 6000); return () => clearTimeout(timer); }, [toast, held]);
  useEffect(() => { if (toast?.focus) undoButton.current?.focus(); }, [toast]);
  const element = toast && <div className="toast" role="status" onFocus={() => setHeld(true)}
    onBlur={e => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setHeld(false); }}><span>{toast.message}</span>
    {toast.undo && <button ref={undoButton} type="button" disabled={busy} onClick={() => {
      const undo = toast.undo!; show(null); setBusy(true);
      void undo().then(async () => { await onUndone?.(); show({ message: undoneMessage }); })
        .catch(e => show({ message: (e as Error).message })).finally(() => setBusy(false));
    }}>Undo</button>}</div>;
  return { element, show };
}
