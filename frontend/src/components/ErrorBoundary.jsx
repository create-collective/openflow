import { Component } from "react";
import Button from "./ui/Button";

/**
 * Catch a render crash and SAY SO, instead of tearing the whole app down silently.
 *
 * Why this exists. `Bindings` threw `ReferenceError: useDoneFlag is not defined` after a Vite
 * hot-reload went stale. React has no error boundary by default, so it unmounted the entire tree
 * -- every page, the nav, everything. What the user saw was a window that had stopped responding
 * to clicks, and what they reported was "the layer list locks up the whole screen".
 *
 * Three rounds of fixes went into the drag handling on that assumption. The drag code was fine.
 * The console had said `ReferenceError` in plain text the entire time, and nothing surfaced it.
 *
 * So this is not defensive decoration -- an invisible crash cost hours of looking in the wrong
 * place. A page that fails should fail loudly, name itself, and leave the rest of the app usable.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Keep it in the console too: the message below is for a person, this is for a stack trace.
    console.error("[OpenFlow] render crash:", error, info?.componentStack);
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="crash">
        <h2 className="crash-title">This page failed to render</h2>
        <p className="crash-lede">
          The rest of the app still works — switch pages using the sidebar. Nothing was written to
          your keyboard, and nothing was saved.
        </p>
        <pre className="crash-error">{String(error?.message || error)}</pre>
        {/* After a hot-reload goes stale this is by far the most common cause, and a reload is
            the whole fix -- worth saying before someone goes hunting through the code. */}
        <p className="crash-hint">
          If you are running the dev server, a hard reload (<kbd>Ctrl</kbd>+<kbd>Shift</kbd>+
          <kbd>R</kbd>) clears a stale hot-reload, which causes this more often than a real bug.
        </p>
        <div className="btn-row">
          <Button variant="primary" onClick={() => this.setState({ error: null, info: null })}>
            Try again
          </Button>
          <Button onClick={() => window.location.reload()}>Reload</Button>
        </div>
        {info?.componentStack && (
          <details className="crash-stack">
            <summary>Component stack</summary>
            <pre>{info.componentStack}</pre>
          </details>
        )}
      </div>
    );
  }
}
