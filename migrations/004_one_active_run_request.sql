-- At most one "collect now" request can be pending or running; concurrent POSTs can no longer both pass.
CREATE UNIQUE INDEX run_requests_one_active ON run_requests ((true)) WHERE status IN ('pending', 'running');
