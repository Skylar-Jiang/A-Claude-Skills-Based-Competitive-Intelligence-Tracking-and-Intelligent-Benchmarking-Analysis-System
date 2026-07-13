# Contribution guide

Keep changes small and contract-driven. Write a failing test first, implement only what makes it pass,
then run focused and full gates. Preserve the Demo/Mock/Real boundary and never conceal missing Real
configuration with fallback behavior.

Do not implement work assigned to another teammate without coordination. Generated data and reports
stay untracked. Pull requests should state whether a change affects API, Pydantic schemas, repository
ports, graph state fields, node routing, or data-origin guarantees.
