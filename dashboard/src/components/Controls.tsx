import { useState } from 'react'
import { api } from '../api'

export default function Controls() {
  const [paused, setPaused] = useState(false)
  const [estopEngaged, setEstopEngaged] = useState(false)

  const handlePause = async () => {
    await api.pauseAll()
    setPaused(true)
  }

  const handleResume = async () => {
    await api.resumeAll()
    setPaused(false)
  }

  const handleEstop = async () => {
    if (!confirm('EMERGENCY STOP — This will immediately halt ALL streams. Continue?')) return
    setEstopEngaged(true)
    await api.emergencyStop()
    setPaused(true)
  }

  return (
    <div className="controls-bar">
      {!paused ? (
        <button className="btn-ctrl btn-pause" onClick={handlePause}>⏸ Pause All</button>
      ) : (
        <button className="btn-ctrl btn-resume" onClick={handleResume}>▶ Resume All</button>
      )}
      <button className={`btn-ctrl btn-estop${estopEngaged ? ' engaged' : ''}`} onClick={handleEstop}>
        ⛔ Emergency Stop
      </button>
    </div>
  )
}
