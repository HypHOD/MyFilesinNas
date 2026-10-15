import { http } from './http'

export interface ProgramStatus {
  status: boolean
  version: string
  first_run: boolean
}

export const getStatus = () =>
  http.get<ProgramStatus>('/program/status').then((r) => r.data)

export const startProgram = () => http.post('/program/start').then((r) => r.data)

export const stopProgram = () => http.post('/program/stop').then((r) => r.data)

export const restartProgram = () =>
  http.post('/program/restart').then((r) => r.data)
