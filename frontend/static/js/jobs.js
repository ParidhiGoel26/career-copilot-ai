/**
 * Handle sync (200) or async (202 + job_id) JSON API responses.
 * Polls GET /jobs/<id> until done|failed.
 *
 * options.onStatus?.(status) — optional UI callback while polling
 */
async function fetchJsonMaybeAsync(url, options = {}, pollMs = 400) {
  const onStatus = options.onStatus;
  const fetchOpts = { ...options };
  delete fetchOpts.onStatus;

  const res = await fetch(url, fetchOpts);
  const data = await res.json().catch(() => ({}));

  if (res.status !== 202 || !data.job_id) {
    if (!res.ok && data.error) {
      const err = new Error(data.error);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  const jobId = data.job_id;
  if (onStatus) onStatus("queued");
  const deadline = Date.now() + 120000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, pollMs));
    const poll = await fetch(`/jobs/${jobId}`);
    const body = await poll.json().catch(() => ({}));
    if (!poll.ok) {
      throw new Error(body.error || "Job not found");
    }
    if (onStatus) onStatus(body.status);
    if (body.status === "done") {
      return body.result || {};
    }
    if (body.status === "failed") {
      throw new Error(body.error || "Job failed");
    }
  }
  throw new Error("Timed out waiting for job");
}
