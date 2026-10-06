## 2026-10-06: add a local search index for unresolved sources

Added an independent search index for per source recovery packets. It validates full source coverage and hashes against a read only work index. Equivalent query groups reduce repeated requests without assigning a shared work identity.

Title only records remain review candidates. The index retains source identifiers, original paths and upstream claims, with identity and rights uncertainty explicit. Source data and local experiments stay outside the repository.

Validation covers source separation, shared queries, accent insensitive search, literal query operators, incomplete coverage, duplicate keys and invalid identity or rights claims. The ongoing provider lookup uses its existing pinned runtime.
