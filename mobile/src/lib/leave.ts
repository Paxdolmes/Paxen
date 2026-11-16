/** What the "leave" block on Today should say. Pure, so it can be tested in Node. */
export interface LeaveByLike {
  at: string
  train_at: string
  line_name: string | null
  stop: string
}

export type LeaveAdvice =
  | { kind: 'later'; at: string } // the commute hasn't started: a forecast for its start time
  | { kind: 'now'; train: LeaveByLike | null } // set off now (train: the one you'd be going for, if known)
  | { kind: 'wait'; at: string; inMin: number; train: LeaveByLike } // you have a few minutes in hand

export function leaveAdvice(departAt: string, leaveBy: LeaveByLike | null | undefined, now: number): LeaveAdvice {
  const depart = new Date(departAt).getTime()
  if (depart - now > 90_000) return { kind: 'later', at: departAt }
  if (!leaveBy) return { kind: 'now', train: null }
  const inMin = Math.floor((new Date(leaveBy.at).getTime() - now) / 60_000)
  // Past the train itself, the forecast is out of date: say nothing about it until the next refresh.
  if (new Date(leaveBy.train_at).getTime() <= now) return { kind: 'now', train: null }
  return inMin >= 1 ? { kind: 'wait', at: leaveBy.at, inMin, train: leaveBy } : { kind: 'now', train: leaveBy }
}
