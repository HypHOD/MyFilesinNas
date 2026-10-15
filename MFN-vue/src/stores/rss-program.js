import { defineStore } from 'pinia'
import { ref } from 'vue'

import * as programApi from '~/api/rss/program'

export const useRssProgramStore = defineStore('rss-program', () => {
  const status = ref(null)

  async function refresh() {
    status.value = await programApi.getStatus()
  }

  async function start() {
    await programApi.startProgram()
    await refresh()
  }

  async function stop() {
    await programApi.stopProgram()
    await refresh()
  }

  async function restart() {
    await programApi.restartProgram()
    await refresh()
  }

  return { status, refresh, start, stop, restart }
})
