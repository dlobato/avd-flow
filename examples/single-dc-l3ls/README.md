# Single-DC L3LS example

This small fabric is based on Arista AVD's `examples/single-dc-l3ls` inventory.
It contains two spines, one MLAG leaf pair, and one tenant SVI.

Run it without initializing a project:

```shell
cd examples/single-dc-l3ls
avd-flow build --avd-version 6.3.0 --inventory inventory.yml
```

Generated configurations and documentation are written below this directory
and ignored by Git.
