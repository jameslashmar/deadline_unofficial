# Deadline resources

Guides and links for running Cinema 4D (and friends) on AWS Thinkbox Deadline. Migrated from the
old Notion wiki in November 2026; this folder is now the maintained copy.

## Guides

### Cinema 4D submitter patches

| Guide | Patch files |
|---|---|
| [Patching the C4D 2023 submitter](patching-c4d-2023-submitter.md) | [`C4D_2023`](../C4D_2023) |
| [Patching the C4D 2024 submitter](patching-c4d-2024-submitter.md) | [`C4D_2024`](../C4D_2024) |
| [Patching the C4D 2025 submitter](patching-c4d-2025-submitter.md) | [`C4D_2025.1.0`](../C4D_2025.1.0) |

For 2026 and 2027 see the [main README](../README.md#c4d-submitter-client-2026).

### Licensing and rendering

- [Forcing command-line licences (C4D 2024)](forcing-command-line-licenses.md)
- [Rendering frames per GPU](rendering-frames-per-gpu.md)
- [Usage-based licensing (UBL) rendering](ubl-rendering.md)
- [After Effects and Deadline](after-effects-and-deadline.md)
- [Unreal Engine 5.3 submitter](unreal-engine-5.3-submitter.md)

## Links

| Topic | Link |
|---|---|
| Setting up the Thinkbox Marketplace for UBL | <https://marketplace.thinkboxsoftware.com/> |
| UBL credits (Thinkbox customer portal) | <https://thinkbox.flexnetoperations.com/> |
| Deadline Launcher | [Deadline docs: Launcher](https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/launcher.html) |
| `deadline.ini` config | [Deadline docs: Client configuration](https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/client-config.html) |
| DeadlineCommand secrets management (handy for debugging UBL) | [Deadline docs: Secrets management](https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/secrets-management/deadline-secrets-management.html) |
| Deadline CPU/GPU affinity and GPU mapping | [AWS Thinkbox blog: CPU and GPU affinity in Deadline](https://www.awsthinkbox.com/blog/cpu-and-gpu-affinity-in-deadline) |
