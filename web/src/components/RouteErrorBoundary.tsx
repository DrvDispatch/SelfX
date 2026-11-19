import { Component, type ReactNode } from "react";
import { Link } from "react-router-dom";

export default class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="rounded-2xl border border-line bg-surface p-6" role="alert">
        <h1 className="text-lg font-semibold text-fg">This page couldn’t open</h1>
        <div className="mt-3 flex flex-wrap gap-4 text-sm font-medium text-primary">
          <button type="button" onClick={() => window.location.reload()} className="underline">Reload page</button>
          <Link to="/tools" className="underline">Browse tools</Link>
        </div>
      </section>
    );
  }
}
