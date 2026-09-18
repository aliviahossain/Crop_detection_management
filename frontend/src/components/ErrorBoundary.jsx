import { Component } from 'react'

// A render crash in one page used to take the whole app with it.
//
// React unmounts the entire tree when a render throws and nothing catches it,
// so a single bad payload left the user staring at a white screen with no
// nav, no back, and nothing to report beyond "the app is blank". That is the
// worst failure mode available to us on a handset in a field.
//
// Keyed on the route, so walking away from the broken page recovers.
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // Nowhere to ship this offline, but it is the only trace of the crash, so
    // keep it where `adb logcat` / devtools can see it.
    console.error('Page crashed:', error, info?.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="page">
        <div className="alert danger">
          <strong>This page could not be displayed.</strong>
          <p className="small" style={{ marginBottom: 0 }}>
            Something on this screen failed to load. The rest of the app still works. Use the
            menu to go somewhere else.
          </p>
        </div>
        <p className="muted small mono">{this.state.error.message}</p>
      </main>
    )
  }
}
