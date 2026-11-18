import { Component } from 'react'
import { AlertCircle } from 'lucide-react'

/** Catches render errors so one broken page cannot blank the whole app. */
export default class ErrorBoundary extends Component {
  state = { error: null }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    console.error('UI error:', error, info?.componentStack)
  }

  componentDidUpdate(prev) {
    // navigating to another page clears the error
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="mx-auto mt-16 max-w-md rounded-2xl bg-red-50 p-6 text-center text-sm text-red-800 dark:bg-red-500/10 dark:text-red-200">
        <AlertCircle className="mx-auto mb-2 h-6 w-6" />
        <p className="font-semibold">Something went wrong on this page.</p>
        <p className="mt-1 opacity-80">Your data is safe. Try again, or reload the page.</p>
        <div className="mt-4 flex justify-center gap-2">
          <button className="btn-secondary" onClick={() => this.setState({ error: null })}>Try again</button>
          <button className="btn-primary" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </div>
    )
  }
}
