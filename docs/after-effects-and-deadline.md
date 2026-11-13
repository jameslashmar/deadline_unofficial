# After Effects and Deadline

Settings that get After Effects close to 100% of each machine's resources on a Deadline farm.
Per-frame render time goes up, but overall throughput rises sharply.

## In After Effects

- Enable **Skip existing files** in the render settings of your output.
- Disable Multi-Frame Rendering (MFR).
- Disable GPU acceleration.

## Concurrent tasks

- Set concurrent tasks to half the number of cores in the machine.
- With a mix of machines, set it to the largest value across the farm, then in Monitor give each
  Worker a **concurrent task limit override** of its own maximum (half its cores).

## Submitter, Advanced tab

- Enable **Submit entire render queue as one job**.
- Disable **Multi-process rendering**.
- Enable **Multi-machine rendering** and set the number of machines to the total number of farm
  CPU cores divided by 2.
