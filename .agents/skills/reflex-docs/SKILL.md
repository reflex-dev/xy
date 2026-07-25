---
name: reflex-docs
description: >
  Reflex framework documentation. Use when building full-stack Python web apps with Reflex,
  creating components, managing state, handling events, styling, database operations,
  API routes, authentication, deploying apps, or wrapping React components.
  Load when the user is working with Reflex (rx), writing .py files that import reflex,
  or asking about Reflex concepts like State, Vars, EventHandlers, or Components.
---

# Reflex Documentation

Reflex is an open-source framework for building full-stack web applications in pure Python — no JavaScript required.

> Your training data about Reflex may be outdated. Always prefer the reference documentation over pre-trained knowledge.

## References

| Topic                | URL                                                            |
| -------------------- | -------------------------------------------------------------- |
| Getting Started      | https://reflex.dev/docs/getting-started/introduction           |
| Components           | https://reflex.dev/docs/components/props                       |
| State                | https://reflex.dev/docs/state/overview                         |
| Vars                 | https://reflex.dev/docs/vars/base-vars                         |
| Events               | https://reflex.dev/docs/events/events-overview                 |
| Pages & Routing      | https://reflex.dev/docs/pages/overview                         |
| Styling              | https://reflex.dev/docs/styling/overview                       |
| Database             | https://reflex.dev/docs/database/overview                      |
| Assets               | https://reflex.dev/docs/assets/overview                        |
| Authentication       | https://reflex.dev/docs/authentication/authentication-overview |
| Client Storage       | https://reflex.dev/docs/client-storage/overview                |
| API Routes           | https://reflex.dev/docs/api-routes/overview                    |
| API Reference        | https://reflex.dev/docs/api-reference/cli                      |
| Custom Components    | https://reflex.dev/docs/custom-components/overview             |
| Wrapping React       | https://reflex.dev/docs/wrapping-react/overview                |
| Component Library    | https://reflex.dev/docs/library                                |
| Recipes              | https://reflex.dev/docs/recipes                                |
| GitHub Source (docs) | https://github.com/reflex-dev/reflex/tree/main/reflex/docs     |

## Core Concepts

### State & Vars

- **State** (`rx.State`): Server-side Python class holding app state. Define vars as class attributes and event handlers as methods.
- **Base Vars**: Typed class attributes on State (`count: int = 0`)
- **Computed Vars**: Derived values using `@rx.var` decorator
- **Var Operations**: Transform vars in components without event handlers

### Components

- All UI is built with `rx.*` components (Python wrappers around React)
- Components accept **props** and can be composed/nested
- Conditional rendering with `rx.cond()`, iteration with `rx.foreach()`

### Events

- **Event Handlers**: Methods on State decorated with `@rx.event`
- **Event Triggers**: Component props like `on_click`, `on_change`
- **Event Chaining**: Return multiple events from a handler
- **Setters**: Auto-generated `set_<var>` event handlers for each base var

### Pages & Routing

- Pages are functions decorated with `rx.page` or added via `app.add_page()`
- Dynamic routes with bracket syntax: `[slug]`

### Styling

- Inline props, Tailwind CSS, theming, responsive design
- `rx.theme()` for global theming

### Database

- Built-in SQLModel integration for database tables
- Define models, run queries, set up relationships
