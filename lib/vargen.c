/*
** Copyright (C) 2016-2018 University of Oxford
**
** This file is part of msprime.
**
** msprime is free software: you can redistribute it and/or modify
** it under the terms of the GNU General Public License as published by
** the Free Software Foundation, either version 3 of the License, or
** (at your option) any later version.
**
** msprime is distributed in the hope that it will be useful,
** but WITHOUT ANY WARRANTY; without even the implied warranty of
** MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
** GNU General Public License for more details.
**
** You should have received a copy of the GNU General Public License
** along with msprime.  If not, see <http://www.gnu.org/licenses/>.
*/
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <stdlib.h>

#include "trees.h"

void
vargen_print_state(vargen_t *self, FILE *out)
{
    fprintf(out, "vargen state\n");
    fprintf(out, "tree_site_index = %d\n", (int) self->tree_site_index);
}

static int
vargen_next_tree(vargen_t *self)
{
    int ret = 0;

    ret = sparse_tree_next(&self->tree);
    if (ret == 0) {
        self->finished = 1;
    } else if (ret < 0) {
        goto out;
    }
    self->tree_site_index = 0;
out:
    return ret;
}

int
vargen_alloc(vargen_t *self, tree_sequence_t *tree_sequence, int flags)
{
    int ret = MSP_ERR_NO_MEMORY;
    table_size_t max_alleles = 4;

    assert(tree_sequence != NULL);
    memset(self, 0, sizeof(vargen_t));

    self->num_samples = tree_sequence_get_num_samples(tree_sequence);
    self->num_sites = tree_sequence_get_num_sites(tree_sequence);
    self->tree_sequence = tree_sequence;
    self->flags = flags;
    if (self->flags & MSP_16_BIT_GENOTYPES) {
        self->variant.genotypes.u16 = malloc(
            self->num_samples * sizeof(*self->variant.genotypes.u16));
    } else {
        self->variant.genotypes.u8 = malloc(
            self->num_samples * sizeof(*self->variant.genotypes.u8));
    }
    self->variant.max_alleles = max_alleles;
    self->variant.alleles = malloc(max_alleles * sizeof(*self->variant.alleles));
    self->variant.allele_lengths = malloc(max_alleles
            * sizeof(*self->variant.allele_lengths));
    /* Because genotypes is a union we can check the pointer */
    if (self->variant.genotypes.u8 == NULL || self->variant.alleles == NULL
            || self->variant.allele_lengths == NULL) {
        ret = MSP_ERR_NO_MEMORY;
        goto out;
    }
    ret = tree_sequence_get_sample_index_map(tree_sequence, &self->sample_index_map);
    if (ret != 0) {
        goto out;
    }
    ret = sparse_tree_alloc(&self->tree, tree_sequence, MSP_SAMPLE_LISTS);
    if (ret != 0) {
        goto out;
    }
    self->finished = 0;
    self->tree_site_index = 0;
    ret = sparse_tree_first(&self->tree);
    if (ret < 0) {
        goto out;
    }
    ret = 0;
out:
    return ret;
}

int
vargen_free(vargen_t *self)
{
    sparse_tree_free(&self->tree);
    msp_safe_free(self->variant.genotypes.u8);
    msp_safe_free(self->variant.alleles);
    msp_safe_free(self->variant.allele_lengths);
    return 0;
}

static int
vargen_expand_alleles(vargen_t *self)
{
    int ret = 0;
    variant_t *var = &self->variant;
    void *p;
    table_size_t hard_limit = UINT8_MAX;

    if (self->flags & MSP_16_BIT_GENOTYPES) {
        hard_limit = UINT16_MAX;
    }
    if (var->max_alleles == hard_limit) {
        ret = MSP_ERR_TOO_MANY_ALLELES;
        goto out;
    }
    var->max_alleles = MSP_MIN(hard_limit, var->max_alleles * 2);
    p = realloc(var->alleles, var->max_alleles * sizeof(*var->alleles));
    if (p == NULL) {
        ret = MSP_ERR_NO_MEMORY;
        goto out;
    }
    var->alleles = p;
    p = realloc(var->allele_lengths, var->max_alleles * sizeof(*var->allele_lengths));
    if (p == NULL) {
        ret = MSP_ERR_NO_MEMORY;
        goto out;
    }
    var->allele_lengths = p;
out:
    return ret;
}

/* The following pair of functions are identical except one handles 8 bit
 * genotypes and the other handles 16 bit genotypes. This is done for performance
 * reasons as this is a key function and for common alleles can entail
 * iterating over millions of samples. The compiler hints are included for the
 * same reason */
static int WARN_UNUSED
vargen_update_genotypes_u8(vargen_t *self, node_id_t node, table_size_t derived)
{
    uint8_t *restrict genotypes = self->variant.genotypes.u8;
    const node_id_t *restrict list_left = self->tree.sample_list_left;
    const node_id_t *restrict list_right = self->tree.sample_list_right;
    const node_id_t *restrict list_next = self->tree.sample_list_next;
    node_id_t index, stop;
    int ret = 0;

    assert(derived < UINT8_MAX);

    index = list_left[node];
    if (index != MSP_NULL_NODE) {
        stop = list_right[node];
        while (true) {
            if (genotypes[index] == derived) {
                ret = MSP_ERR_INCONSISTENT_MUTATIONS;
                goto out;
            }
            genotypes[index] = (uint8_t) derived;
            if (index == stop) {
                break;
            }
            index = list_next[index];
        }
    }
out:
    return ret;
}

static int WARN_UNUSED
vargen_update_genotypes_u16(vargen_t *self, node_id_t node, table_size_t derived)
{
    uint16_t *restrict genotypes = self->variant.genotypes.u16;
    const node_id_t *restrict list_left = self->tree.sample_list_left;
    const node_id_t *restrict list_right = self->tree.sample_list_right;
    const node_id_t *restrict list_next = self->tree.sample_list_next;
    node_id_t index, stop;
    int ret = 0;

    assert(derived < UINT16_MAX);

    index = list_left[node];
    if (index != MSP_NULL_NODE) {
        stop = list_right[node];
        while (true) {
            if (genotypes[index] == derived) {
                ret = MSP_ERR_INCONSISTENT_MUTATIONS;
                goto out;
            }
            genotypes[index] = (uint16_t) derived;
            if (index == stop) {
                break;
            }
            index = list_next[index];
        }
    }
out:
    return ret;
}

static int
vargen_update_site(vargen_t *self)
{
    int ret = 0;
    table_size_t j, derived;
    variant_t *var = &self->variant;
    site_t *site = var->site;
    mutation_t mutation;

    /* Ancestral state is always allele 0 */
    var->alleles[0] = site->ancestral_state;
    var->allele_lengths[0] = site->ancestral_state_length;
    var->num_alleles = 1;

    /* The algorithm for generating the allelic state of every sample works by
     * examining each mutation in order, and setting the state for all the
     * samples under the mutation's node. For complex sites where there is
     * more than one mutation, we depend on the ordering of mutations being
     * correct. Specifically, any mutation that is above another mutation in
     * the tree must be visited first. This is enforced using the mutation.parent
     * field, where we require that a mutation's parent must appear before it
     * in the list of mutations. This guarantees the correctness of this algorith.
     */
    if (self->flags & MSP_16_BIT_GENOTYPES) {
        memset(self->variant.genotypes.u16, 0, 2 * self->num_samples);
    } else {
        memset(self->variant.genotypes.u8, 0, self->num_samples);
    }
    for (j = 0; j < site->mutations_length; j++) {
        mutation = site->mutations[j];
        /* Compute the allele index for this derived state value. */
        derived = 0;
        while (derived < var->num_alleles) {
            if (mutation.derived_state_length == var->allele_lengths[derived]
                    && memcmp(mutation.derived_state, var->alleles[derived],
                        var->allele_lengths[derived]) == 0) {
                break;
            }
            derived++;
        }
        if (derived == var->num_alleles) {
            if (var->num_alleles == var->max_alleles) {
                ret = vargen_expand_alleles(self);
                if (ret != 0) {
                    goto out;
                }
            }
            var->alleles[derived] = mutation.derived_state;
            var->allele_lengths[derived] = mutation.derived_state_length;
            var->num_alleles++;
        }

        if (self->flags & MSP_16_BIT_GENOTYPES) {
            ret = vargen_update_genotypes_u16(self, mutation.node, derived);
        } else {
            ret = vargen_update_genotypes_u8(self, mutation.node, derived);
        }
        if (ret != 0) {
            goto out;
        }
    }
out:
    return ret;
}

int
vargen_next(vargen_t *self, variant_t **variant)
{
    int ret = 0;

    bool not_done = true;

    if (!self->finished) {
        while (not_done && self->tree_site_index == self->tree.sites_length) {
            ret = vargen_next_tree(self);
            if (ret < 0) {
                goto out;
            }
            not_done = ret == 1;
        }
        if (not_done) {
            self->variant.site = &self->tree.sites[self->tree_site_index];
            ret = vargen_update_site(self);
            if (ret != 0) {
                goto out;
            }
            self->tree_site_index++;
            *variant = &self->variant;
            ret = 1;
        }
    }
out:
    return ret;
}
