/**
 * Main-thread driver for the worker-based sync-access-handle probe.
 *
 * `FileSystemSyncAccessHandle` is `[Exposed=DedicatedWorker]`, so the main
 * thread can't detect it by inspecting prototypes — it has to ask a worker
 * that actually tries to acquire one. See `./probe.worker`.
 */

const PROBE_TIMEOUT_MS = 5_000

/** Whether a DedicatedWorker can acquire an OPFS sync access handle. */
export async function checkSyncAccessHandle(): Promise<boolean> {
  if (typeof Worker === 'undefined') return false

  let worker: Worker
  try {
    worker = new Worker(new URL('./probe.worker.ts', import.meta.url), {
      type: 'module',
    })
  } catch {
    return false
  }

  try {
    return await new Promise<boolean>((resolve) => {
      // Resolve false if the worker never reports back — a hung probe must
      // not block app boot.
      const timer = setTimeout(() => resolve(false), PROBE_TIMEOUT_MS)
      worker.onmessage = (event: MessageEvent<{ ok?: boolean }>) => {
        clearTimeout(timer)
        resolve(event.data?.ok === true)
      }
      worker.onerror = () => {
        clearTimeout(timer)
        resolve(false)
      }
      worker.postMessage('probe')
    })
  } finally {
    worker.terminate()
  }
}
