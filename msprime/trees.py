#
# Copyright (C) 2014 Jerome Kelleher <jerome.kelleher@well.ox.ac.uk>
#
# This file is part of msprime.
#
# msprime is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# msprime is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with msprime.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Module responsible to generating and reading tree files.
"""
from __future__ import print_function
from __future__ import division

import os
import random
import tempfile

import _msprime
from _msprime import sort_tree_file
from _msprime import InputError
from _msprime import LibraryError

def harmonic_number(n):
    """
    Returns the nth Harmonic number.
    """
    return sum(1 / k for k in range(1, n + 1))

def simulate_trees(sample_size, num_loci, scaled_recombination_rate,
        population_models=[], max_memory="10M"):
    """
    Simulates the coalescent with recombination under the specified model
    parameters and returns an iterator over the resulting trees.
    """
    fd, tf = tempfile.mkstemp(prefix="msp_", suffix=".dat")
    os.close(fd)
    try:
        sim = TreeSimulator(sample_size, tf)
        sim.set_num_loci(num_loci)
        sim.set_scaled_recombination_rate(scaled_recombination_rate)
        sim.set_max_memory(max_memory)
        for m in population_models:
            sim.add_population_model(m)
        sim.run()
        # We are done with the simulator so free up the memory
        del sim
        sort_tree_file(tf)
        tree_file = TreeFile(tf)
        for l, pi, tau in tree_file:
            yield l, pi, tau
        tree_file.close()
    finally:
        os.unlink(tf)

def simulate_tree(sample_size, population_models=[], max_memory="10M"):
    """
    Simulates the coalescent at a single locus for the specified sample size
    under the specified list of population models.
    """
    iterator = simulate_trees(sample_size, 1, 0, population_models, max_memory)
    l, pi, tau = next(iterator)
    return pi, tau

class TreeSimulator(object):
    """
    Class to simulate trees under the standard neutral coalescent with
    recombination.
    """
    def __init__(self, sample_size, tree_file_name):
        self._sample_size = sample_size
        self._tree_file_name = tree_file_name
        self._scaled_recombination_rate = 1.0
        self._num_loci = 1
        self._population_models = []
        self._random_seed = None
        self._segment_block_size = None
        self._avl_node_block_size = None
        self._node_mapping_block_size = None
        self._max_memory = None
        self._ll_sim = None

    def get_num_breakpoints(self):
        return self._ll_sim.get_num_breakpoints()

    def get_time(self):
        return self._ll_sim.get_time()

    def get_num_avl_node_blocks(self):
        return self._ll_sim.get_num_avl_node_blocks()

    def get_num_node_mapping_blocks(self):
        return self._ll_sim.get_num_node_mapping_blocks()

    def get_num_segment_blocks(self):
        return self._ll_sim.get_num_segment_blocks()

    def get_num_coancestry_events(self):
        return self._ll_sim.get_num_coancestry_events()

    def get_num_recombination_events(self):
        return self._ll_sim.get_num_recombination_events()

    def add_population_model(self, pop_model):
        self._population_models.append(pop_model)

    def set_num_loci(self, num_loci):
        self._num_loci = num_loci

    def set_scaled_recombination_rate(self, scaled_recombination_rate):
        self._scaled_recombination_rate = scaled_recombination_rate

    def set_effective_population_size(self, effective_population_size):
        self._effective_population_size = effective_population_size

    def set_random_seed(self, random_seed):
        self._random_seed = random_seed

    def set_segment_block_size(self, segment_block_size):
        self._segment_block_size = segment_block_size

    def set_avl_node_block_size(self, avl_node_block_size):
        self._avl_node_block_size = avl_node_block_size

    def set_node_mapping_block_size(self, node_mapping_block_size):
        self._node_mapping_block_size = node_mapping_block_size

    def set_max_memory(self, max_memory):
        """
        Sets the approximate maximum memory used by the simulation
        to the specified value.  This can be suffixed with
        K, M or G to specify units of Kibibytes, Mibibytes or Gibibytes.
        """
        s = max_memory
        d = {"K":2**10, "M":2**20, "G":2**30}
        multiplier = 1
        value = s
        if s.endswith(tuple(d.keys())):
            value = s[:-1]
            multiplier = d[s[-1]]
        n = int(value)
        self._max_memory = n * multiplier

    def _set_environment_defaults(self):
        """
        Sets sensible default values for the memory usage parameters.
        """
        # Set the block sizes using our estimates.
        n = self._sample_size
        m = self._num_loci
        rho = 4 * self._scaled_recombination_rate * (m - 1)
        num_trees = min(m // 2, rho * harmonic_number(n - 1))
        b = 10 # Baseline maximum
        num_trees = max(b, int(num_trees))
        num_avl_nodes = max(b, 4 * n + num_trees)
        num_segments = max(b, int(0.0125 * n  * rho))
        if self._avl_node_block_size is None:
            self._avl_node_block_size = num_avl_nodes
        if self._segment_block_size is None:
            self._segment_block_size = num_segments
        if self._node_mapping_block_size is None:
            self._node_mapping_block_size = num_trees
        if self._random_seed is None:
            self._random_seed = random.randint(0, 2**31 - 1)
        if self._max_memory is None:
            self._max_memory = 10 * 1024 * 1024 # 10MiB by default

    def run(self):
        """
        Runs the simulation until complete coalescence has occured.
        """
        models = [m.get_ll_model() for m in self._population_models]
        assert self._ll_sim is None
        self._set_environment_defaults()
        self._ll_sim = _msprime.Simulator(sample_size=self._sample_size,
                num_loci=self._num_loci, population_models=models,
                scaled_recombination_rate=self._scaled_recombination_rate,
                random_seed=self._random_seed,
                tree_file_name=self._tree_file_name,
                max_memory=self._max_memory,
                segment_block_size=self._segment_block_size,
                avl_node_block_size=self._avl_node_block_size,
                node_mapping_block_size=self._node_mapping_block_size)
        # This will change to return True/False when we support partial
        # simulations.
        return self._ll_sim.run()

    def reset(self):
        """
        Resets the simulation so that we can perform another replicate.
        """
        self._ll_sim = None


class TreeFile(object):
    """
    Class to read trees from a tree file generated by the msprime simulation.
    """
    def __init__(self, tree_file_name):
        self._ll_tree_file = _msprime.TreeFile(tree_file_name)

    def close(self):
        self._ll_tree_file = None

    def issorted(self):
        return self._ll_tree_file.issorted()

    def iscomplete(self):
        return self._ll_tree_file.iscomplete()

    def get_sample_size(self):
        return self._ll_tree_file.get_sample_size()

    def get_num_loci(self):
        return self._ll_tree_file.get_num_loci()

    def get_num_trees(self):
        return self._ll_tree_file.get_num_trees()

    def get_metadata(self):
        return self._ll_tree_file.get_metadata()

    def __iter__(self):
        return self.trees()

    def trees(self):
        assert self._ll_tree_file.issorted()
        n = 2 * self.get_sample_size()
        pi = [0 for j in range(n)]
        tau = [0 for j in range(n)]
        # Set the unused element to -1 following Knuth's convention.
        pi[0] = -1
        tau[0] = -1
        b = 1
        for l, c1, c2, p, t in self._ll_tree_file:
            if l != b:
                yield l - b, pi, tau
                b = l
            pi[c1] = p
            pi[c2] = p
            tau[p] = t
        yield self.get_num_loci() - l + 1, pi, tau

    def records(self):
        return self._ll_tree_file

# The haplotype generator is being done in Python for the time being.
# This definitely needs to get moved down to C once the algorithm is
# fully sorted out. We can lose these imports then.
import numpy as np
import numpy.random
import json

def isdescendent(u, v, pi):
    """
    Returns True if the node u is a descendent of the node v in the
    specified oriented forest pi.
    """
    j = u
    while j != v and j != 0:
        j = pi[j]
    # print("isdescendent", u, v, pi, j == v)
    return j == v


class HaplotypeGenerator(object):
    """
    Class that takes a TreeFile and a recombination rate and builds a set
    of haplotypes consistent with the underlying trees.
    """
    def __init__(self, tree_file_name, mutation_rate):
        self._tree_file = TreeFile(tree_file_name)
        self._mutation_rate = mutation_rate
        self._num_segregating_sites = 0
        self._sample_size = self._tree_file.get_sample_size()
        self._haplotypes = ['' for j in range(self._sample_size + 1)]
        self._positions = []
        self._generate_haplotypes()

    def _generate_haplotypes(self):
        m = json.loads(self._tree_file.get_metadata())
        seed = m["random_seed"]
        np.random.seed(seed)
        n = self._sample_size
        pi = [0 for j in range(2 * n)]
        tau = [0 for j in range(2 * n)]
        b = 1
        sequences = self._haplotypes
        mu = self._mutation_rate
        # This algorithm basically works, we just need to actually prove
        # it. It'll all hang on the fact that records are sorted in time
        # order, so that we never get the wrong time in between trees.
        mutations = []
        for l, c1, c2, p, t in self._tree_file.records():
            # print(l, c1, c2, p, t)
            for c in [c1, c2]:
                k = np.random.poisson(mu * (t - tau[c]))
                if k > 0:
                    # print(k, "mutations happened on ", c, "->", p)
                    mutations.append((c, k))
            if l != b:
                # print("new tree:",  l - b, pi, tau)
                # print("applying mutations")
                for c, k in mutations:
                    for mut in range(k):
                        for j in range(1, n + 1):
                            v = str(int(isdescendent(j, c, pi)))
                            sequences[j] += v
                b = l
                mutations = []
            pi[c1] = p
            pi[c2] = p
            tau[p] = t


    def get_num_segregating_sites(self):
        return len(self._haplotypes[1])

    def get_haplotypes(self):
        return self._haplotypes[1:]

    def get_positions(self):
        return [0 for j in range(self.get_num_segregating_sites())]

class PopulationModel(object):
    """
    Superclass of simulation population models.
    """
    def __init__(self, start_time):
        self.start_time = start_time

    def get_ll_model(self):
        """
        Returns the low-level model corresponding to this population
        model.
        """
        return self.__dict__

class ConstantPopulationModel(PopulationModel):
    """
    Class representing a constant-size population model. The size of this
    is expressed relative to the size of the population at sampling time.
    """
    def __init__(self, start_time, size):
        super(ConstantPopulationModel, self).__init__(start_time)
        self.size = size
        self.type = _msprime.POP_MODEL_CONSTANT


class ExponentialPopulationModel(PopulationModel):
    """
    Class representing an exponentially growing or shrinking population.
    TODO document model.
    """
    def __init__(self, start_time, alpha):
        super(ExponentialPopulationModel, self).__init__(start_time)
        self.alpha = alpha
        self.type = _msprime.POP_MODEL_EXPONENTIAL


def oriented_tree_to_newick(pi, tau):
    """
    Converts the specified oriented tree to an ms-compatible Newick tree.
    """
    # Build a top-down linked tree using a dict. Each node has a list
    # of it's children
    d = {}
    n = len(pi) // 2
    # We also want the branch lengths; time from a node back to its parent
    b = {2 * n - 1: None}
    for j in range(1, n + 1):
        u = j
        d[u] = None
        not_done = True
        while pi[u] != 0 and not_done:
            # ms uses a fixed 3 digit precision; we can easily fix this.
            b[u] = "{0:.3f}".format(tau[pi[u]] - tau[u])
            if pi[u] in d:
                # This is the second time we've seen this node
                not_done = False
            else:
                d[pi[u]] = []
            d[pi[u]].append(u)
            u = pi[u]
    return _build_newick(2 * n - 1, d, b)

def _build_newick(node, tree, branch_lengths):
    l = branch_lengths[node]
    if tree[node] is not None:
        c1, c2 = tree[node]
        s1 = _build_newick(c1, tree, branch_lengths)
        s2 = _build_newick(c2, tree, branch_lengths)
        if l is None:
            # The root node is treated differently
            s = "({0},{1});".format(s1, s2)
        else:
            s = "({0},{1}):{2}".format(s1, s2, l)
    else:
        s = "{0}:{1}".format(node, l)
    return s