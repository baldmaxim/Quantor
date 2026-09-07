# Admin Console information architecture

```text
Dashboard
├─ System status
├─ Recent failures
└─ Version/build

Workspaces
├─ List
├─ Workspace detail
└─ Members

Users & Access
├─ Users
├─ Memberships
├─ Roles
└─ Permissions matrix (read-only where code-defined)

Settings
├─ General
├─ Upload/document defaults
└─ Effective value/provenance

Feature Flags
├─ System flags
└─ Workspace overrides

Integrations
└─ TenderHUB
   ├─ status
   ├─ connection test
   └─ project binding/rebind audit

Model Providers
├─ Providers
├─ Models/capabilities
├─ privacy/local-vs-remote classification
└─ health

Jobs & Workers
├─ queue
├─ failures
├─ attempts
└─ worker status

Storage / System Health
├─ PostgreSQL
├─ migrations
├─ ObjectStorage
├─ OIDC
└─ dependencies

Audit Log
├─ filters
└─ safe diff
```
