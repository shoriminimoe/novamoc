/// <reference lib="webworker" />
/**
 * DedicatedWorker half of the OPFS sync-access-handle probe (ADR-003).
 *
 * `FileSystemSyncAccessHandle` is `[Exposed=DedicatedWorker]`, so support
 * is invisible to the main thread — prototype inspection there reports a
 * false negative in every supporting browser. We don't trust an interface
 * name either: we open OPFS, create a temp file, actually acquire a sync
 * access handle, then clean up. Only a real acquisition proves support.
 */

async function canCreateSyncAccessHandle(): Promise<boolean> {
  try {
    const root = await navigator.storage.getDirectory()
    const name = `.novamoc-probe-${crypto.randomUUID()}`
    const file = await root.getFileHandle(name, { create: true })
    const handle = await file.createSyncAccessHandle()
    handle.close()
    await root.removeEntry(name)
    return true
  } catch {
    return false
  }
}

self.onmessage = async (): Promise<void> => {
  self.postMessage({ ok: await canCreateSyncAccessHandle() })
}
