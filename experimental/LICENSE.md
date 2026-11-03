# License for Experimental Patches

The patch files in this directory (`experimental/*.patch`):
- `elan_0c4f_cumulative_master.patch`
- `elan_0c4f_mr530.patch`
- `elan_0c4f_sigfm_opensource.patch`
- `elan_0c4f_opensource.patch`

modify and derive from upstream **libfprint** and the work of respective GitLab Merge Request contributors (including Natasha England-Elbro, Matthieu Charette, and Yassine Oudjana).

Upstream `libfprint` is licensed under the **GNU Lesser General Public License version 2.1 or later (LGPL-2.1-or-later)**. Consequently, all patches in this directory are distributed under the terms of the:

**GNU Lesser General Public License, Version 2.1 or later (LGPL-2.1+)**

A copy of the GNU Lesser General Public License version 2.1 is available at:
https://www.gnu.org/licenses/old-licenses/lgpl-2.1.en.html

---

### Clarification on Repository Licensing

- **Experimental Patches (`experimental/*.patch`)**: Licensed under **GNU LGPL-2.1+** as derivative works of `libfprint`.
- **Packaging, Scripts, and Tooling**: The helper script (`elan-0c4f.sh`), analysis scripts, and original project documentation are licensed under the **MIT License** set forth in the repository root [`LICENSE`](../LICENSE).
