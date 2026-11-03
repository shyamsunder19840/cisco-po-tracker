import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";
import "./settings.css";

class Boundary extends React.Component {
  state = { err: null };
  static getDerivedStateFromError(err) { return { err }; }
  render() {
    if (this.state.err)
      return <div className="page"><div className="error">Something went wrong: {String(this.state.err.message || this.state.err)}. Reload the page and try a shorter range.</div></div>;
    return this.props.children;
  }
}

createRoot(document.getElementById("root")).render(<Boundary><App /></Boundary>);
