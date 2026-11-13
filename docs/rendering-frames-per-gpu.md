# Rendering frames per GPU

Notes on getting Deadline to render one frame per GPU with Cinema 4D and Redshift, what Deadline
actually does with each combination of settings, and the workaround that works.

## First things first

Open Cinema 4D and check that it sees the same GPUs as Device Manager. They are not always all
there. Deadline has been seen rendering on a CPU's integrated GPU that was disabled in the BIOS,
so disable the CPU device in the C4D Redshift preferences too.

## How Deadline should work

> [!IMPORTANT]
> Use only one of these approaches at a time. The Worker-centric
> [GPU Affinity](https://docs.thinkboxsoftware.com/products/deadline/10.1/1_User%20Manual/manual/worker-config.html#gpu-affinity)
> setting cannot be combined with the submitter's **GPUs Per Task** or **Select GPU Devices**.

These settings should give one frame per GPU:

**C4D submitter**

- Set concurrent tasks to the maximum number of GPUs in a machine (check machine limits).
- Set GPUs per task to 0 (the default).

**Machine overrides**

- Set concurrent tasks to the number of GPUs in the system.
- Set GPU Affinity to the selected GPUs.

**What actually happens:** Deadline starts *x* threads but renders all *x* tasks on the same GPU,
ignoring the others.

**What should happen:** one thread per GPU.

## Another approach

Let Deadline try to handle it:

**C4D submitter**

- Set GPUs per task to 1 (this should use one GPU per thread).

**Machine overrides**

- Set GPU Affinity to the selected GPUs.

This is not really covered in the documentation, but see the
[AWS Thinkbox blog post on CPU and GPU affinity](https://www.awsthinkbox.com/blog/cpu-and-gpu-affinity-in-deadline)
and the note above.

**What actually happens:** Deadline starts *x* threads on *x* GPUs, then renders buckets from
several tasks on each GPU. This is very heavy and very slow.

**What should happen:** one thread per GPU.

## The workaround

**C4D submitter**

- Set concurrent tasks to the maximum number of GPUs in a machine (check machine limits).
- Set GPUs per task to 1.

**Machine overrides**

- Set concurrent tasks to the number of GPUs in the system.
- **Disable GPU Affinity.**

**What actually happens:** all the GPUs in the machine are used, one thread per GPU (through the
concurrent tasks).

**Caveats:** you lose control over which GPUs Deadline uses. A display GPU will be used too, and
limiting concurrent tasks will not avoid it, because the display GPU is usually device 0 and gets
the first task.

This can also pick up the CPU's integrated GPU even when it is disabled in Device Manager. Disable
the iGPU in the BIOS instead; if the option is missing, update the BIOS. This affects AM5 CPUs.

## Using just one GPU

**C4D submitter**

- Set concurrent tasks to the maximum number of GPUs in a machine (check machine limits).

**Machine overrides**

- Set concurrent tasks to 1.
- Set GPU Affinity to a single GPU.

For some reason this works. You can limit the task to one GPU, switch the affinity to the other
GPU, resume the task, and it moves GPUs and renders fine.

Using 2 out of 3 GPUs this way fails unless GPUs per task is 0, and then it renders very slowly
because the tasks are split across the GPUs. In that case use the workaround above.
