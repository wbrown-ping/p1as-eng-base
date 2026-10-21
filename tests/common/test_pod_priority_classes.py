"""Black-box pod priority tier test (PDO-12385).

Asserts the priority-tier contract against a live cluster using only
workload pod-template specs and PriorityClass objects. Class names are
resolved from the workloads and values from the API; no class values are
hardcoded:

  1. The PingDirectory, New Relic, and Fluent Bit workloads all reference a
     PriorityClass that exists in the cluster.
  2. The PingDirectory workload's class (the Critical-tier exemplar) has a
     higher value than the classes on the New Relic and Fluent Bit workloads.
  3. Every PriorityClass with 'vital' in its name has a value below the
     PingDirectory class's value.

Spec-level reads (pod templates, not pod status), so the test is valid while
pods are deploying or mid-rollout.
"""

import unittest

from k8s_utils import K8sUtils

# The workloads covered by the tier model, as (kind, name, namespace).
# PingDirectory is the Critical-tier exemplar; Fluent Bit and the New Relic
# infrastructure workloads are the Vital tier from PDO-12385. The nri-bundle
# chart applies one priorityClassName across the newrelic-infrastructure
# subchart, so the ksm Deployment carries the class alongside the kubelet
# DaemonSet and is asserted too.
WORKLOADS = {
    "pingdirectory": ("statefulset", "pingdirectory", "ping-cloud"),
    "fluent-bit": ("daemonset", "fluent-bit", "elastic-stack-logging"),
    "newrelic-kubelet": ("daemonset", "nri-bundle-nrk8s-kubelet", "newrelic"),
    "newrelic-ksm": ("deployment", "nri-bundle-nrk8s-ksm", "newrelic"),
}

# Substring identifying a vital-tier PriorityClass by name
# (p1as-vital, p1as-vital-base, p1as-vital-observability, ...).
VITAL_NAME_MARKER = "vital"


class TestPodPriorityTiers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kube = K8sUtils()
        cls.class_names = {
            wl: cls.kube.get_workload_priority_class_name(kind, name, ns)
            for wl, (kind, name, ns) in WORKLOADS.items()
        }
        existing_classes = cls.kube.get_priority_class_names()
        cls.class_values = {
            wl: cls.kube.get_priority_class_value(class_name)
            for wl, class_name in cls.class_names.items()
            if class_name and class_name in existing_classes
        }

    def test_workloads_have_existing_priority_class(self):
        """PD, NR, and FLB all reference a PriorityClass that exists."""
        for wl in WORKLOADS:
            with self.subTest(workload=wl):
                class_name = self.class_names[wl]
                self.assertTrue(
                    class_name,
                    f"{wl} has no priorityClassName assigned",
                )
                self.assertIn(
                    wl,
                    self.class_values,
                    f"{wl} references PriorityClass '{class_name}' which "
                    "does not exist in the cluster",
                )

    def test_critical_outranks_vital_workloads(self):
        """The PingDirectory class value exceeds the FLB and NR class values."""
        pd_value = self.class_values.get("pingdirectory")
        self.assertIsNotNone(
            pd_value, "pingdirectory PriorityClass missing (see first test)"
        )
        for wl in ("fluent-bit", "newrelic-kubelet", "newrelic-ksm"):
            with self.subTest(workload=wl):
                wl_value = self.class_values.get(wl)
                self.assertIsNotNone(
                    wl_value, f"{wl} PriorityClass missing (see first test)"
                )
                self.assertGreater(
                    pd_value,
                    wl_value,
                    f"pingdirectory ({self.class_names['pingdirectory']}="
                    f"{pd_value}) does not outrank {wl} "
                    f"({self.class_names[wl]}={wl_value})",
                )

    def test_vital_named_classes_below_critical(self):
        """Every 'vital'-named PriorityClass values below the PD class value."""
        pd_value = self.class_values.get("pingdirectory")
        self.assertIsNotNone(
            pd_value, "pingdirectory PriorityClass missing (see first test)"
        )
        pd_class = self.class_names["pingdirectory"]
        vital_classes = [
            name
            for name in self.kube.get_priority_class_names()
            if VITAL_NAME_MARKER in name.lower()
        ]
        self.assertTrue(
            vital_classes,
            "no vital-tier PriorityClasses found in the cluster "
            f"(expected at least one with '{VITAL_NAME_MARKER}' in the name)",
        )
        for name in vital_classes:
            with self.subTest(priority_class=name):
                self.assertLess(
                    self.kube.get_priority_class_value(name),
                    pd_value,
                    f"vital PriorityClass '{name}' is not below the critical "
                    f"class '{pd_class}' ({pd_value})",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
