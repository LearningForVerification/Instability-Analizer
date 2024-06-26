import copy

import numpy as np

import InstabilityInspector.pynever.strategies.abstraction as abst
from InstabilityInspector.pynever import nodes
from InstabilityInspector.pynever.networks import SequentialNetwork
from InstabilityInspector.pynever.strategies.abstraction import Star
from InstabilityInspector.pynever.strategies.bp.bounds_manager import BoundsManager
from InstabilityInspector.pynever.tensors import Tensor


class RefinementTarget:
    """

    """

    # TODO how to use with ResNets? Layer identifier?
    def __init__(self, layer: int, neuron: int):
        self.layer_idx = layer
        self.neuron_idx = neuron


def get_bounds(nn: SequentialNetwork, prop: 'NeVerProperty', strategy: str) -> dict:
    """
    This function gets the bounds of the neural network for the given property
    of interest. The bounds are computed based on a strategy that allows to
    plug and play different bound propagation algorithms

    Parameters
    ----------
    nn : SequentialNetwork
        The neural network of interest in the internal representation
    prop : NeVerProperty
        The property of interest
    strategy : str
        The strategy to use for computing the bounds [symbolic, lirpa, ...]

    Returns
    ----------
    dict
        The dictionary of the bounds wrapped in an AbstractBounds object for each layer

    """

    if strategy == 'symbolic':
        # Return the pre-activation bounds for ReLU layers
        return BoundsManager(nn, prop).compute_bounds()
    elif strategy == 'lirpa':
        # return something...
        pass
    # TODO add more strategies


def abs_propagation(star: Star, bounds: dict, nn_list: list) -> Star:
    """
    This method performs the abstract propagation of a single star starting
    from a specific layer and neuron. The output is a single star that uses
    approximation in the next layers

    Parameters
    ----------
    star : Star
        The star to process
    bounds : dict
        The bounds of the network layers
    nn_list : list
        The neural network represented as a list

    Returns
    ----------
    Star
        The resulting star approximate with the abstract propagation

    """

    start_layer = star.ref_layer
    neuron_idx = star.ref_neuron

    for layer in nn_list[start_layer:]:
        i = nn_list.index(layer)

        # Propagate fully connected entirely
        if isinstance(layer, nodes.FullyConnectedNode):
            # Need to expand bias since they are memorized like one-dimensional vectors in FC nodes.
            if layer.bias.shape != (layer.weight.shape[0], 1):
                bias = np.expand_dims(layer.bias, 1)
            else:
                bias = layer.bias
            star = abst.single_fc_forward(star, layer.weight, bias).pop()

        # Propagate ReLU starting from target
        elif isinstance(layer, nodes.ReLUNode):
            l_bounds = bounds[layer.identifier]
            if i == start_layer:
                star = abst.approx_relu_forward(star, l_bounds, layer.in_dim[0], start_idx=neuron_idx)
            else:
                star = abst.approx_relu_forward(star, l_bounds, layer.in_dim[0])

        else:
            raise NotImplementedError('Unsupported layer')

    return star


def propagate_until_relu(star: Star, nn_list: list, skip: bool) -> Star:
    """
    This function performs the star propagation throughout Fully Connected layers
    only, until a ReLU layer is encountered. This is used in order to process
    Fully Connected layers only once per cycle

    Parameters
    ----------
    star : Star
        The star to process
    nn_list : list
        The neural network represented as a list

    Returns
    ----------
    Star
        The resulting star before the next ReLU layer

    """

    start_layer = star.ref_layer
    i = 0

    for layer in nn_list[start_layer:]:

        # Propagate fully connected entirely
        if isinstance(layer, nodes.FullyConnectedNode):
            # Need to expand bias since they are memorized like one-dimensional vectors in FC nodes.
            if layer.bias.shape != (layer.weight.shape[0], 1):
                bias = np.expand_dims(layer.bias, 1)
            else:
                bias = layer.bias
            star = abst.single_fc_forward(star, layer.weight, bias).pop()
            i += 1

        elif isinstance(layer, nodes.ReLUNode):
            # If all the neurons have been processed...
            if skip:  # star.ref_neuron == star.center.shape[0] - 1 and skip:
                skip = False
                i += 1
                continue
            # Otherwise, stay on this layer and interrupt cycle
            else:
                break

        else:
            raise NotImplementedError('Unsupported layer')

    # Set reference layer
    star.ref_layer = start_layer + i

    return star


def check_intersection(star: Star, prop: 'NeVerProperty') -> (bool, list):
    """
    This function checks whether a star intersects with the output property
    using a linear program. Since the output property may contain disjunction
    the intersection is computed with all the halfspaces in the output property.
    If an intersection occurs, the resulting star is saved and returned for
    extracting a counterexample

    Parameters
    ----------
    star : Star
        The star to intersect with the output property
    prop : NeVerProperty
        The property of interest

    Returns
    -------
    (bool, list)
        A tuple containing the result of the intersection check (True/False) and
        the list of unfeasible stars. If the result is True the list must contain
        at least one element, otherwise the list must be empty

    """

    intersects = False
    unsafe_stars = []

    # Loop possible disjunctions
    for i in range(len(prop.out_coef_mat)):
        intersection = abst.intersect_with_halfspace(star,
                                                     prop.out_coef_mat[i],
                                                     prop.out_bias_mat[i])
        if not intersection.check_if_empty():
            intersects = True
            unsafe_stars.append(intersection)

    return intersects, unsafe_stars


def intersect_star_lp(current_star, net_list, nn_bounds, prop):
    # Compute the output abstract star from current_star/bounds
    out_star = abs_propagation(current_star, nn_bounds, net_list)

    # Check intersection using a LP
    intersects, unsafe_stars = check_intersection(out_star, prop)

    return intersects, unsafe_stars


def intersect_symb_lp(current_star, net_list, nn_bounds, prop, target):
    output = None
    # output >= nn_bounds[0]['model_out'][1].lower.matrix * x_input + lower.offset
    # output <= nn_bounds[0]['model_out'][1].upper.matrix * x_input + upper.offset
    # y0 >= 0.25 x0
    # y0 <= 0.25 x0 + 0.25
    # I can build a star from this!

    # TODO is it possible to check whether it is fully inside?
    intersects, unsafe_stars = check_intersection(output, prop)
    return intersects, unsafe_stars


def get_next_target(ref_heur: str,
                    star: Star,
                    nn_list: list) -> (RefinementTarget, Star):
    if ref_heur == 'sequential':
        return get_target_sequential(star, nn_list)
    else:
        raise NotImplementedError('Only sequential refinement supported')


def get_target_sequential(star: Star, nn_list: list) -> (RefinementTarget, Star):
    """
    This function updates the target for the refinement of the star using
    a sequential approach. For each ReLU layer all neurons are refined
    sequentially.

    Parameters
    ----------
    star : Star
        The star to refine
    nn_list : list
        The list of the network layers

    Returns
    ----------
    tuple, Star
        The new target for the refinement, which is None when there is no more
        refinement to do for this star, and the propagated star

    """

    def get_last_relu(net_list: list):
        last_relu_idx = 0
        for net_layer in net_list[::-1]:
            if isinstance(net_layer, nodes.ReLUNode):
                last_relu_idx = net_list.index(net_layer)
                break

        return last_relu_idx

    star = propagate_until_relu(star, nn_list, False)
    current_neuron = star.ref_neuron

    if current_neuron < star.center.shape[0]:
        # There are more neurons in the layer: increment the neuron count
        new_target = RefinementTarget(star.ref_layer, current_neuron)

    else:
        if star.ref_layer == get_last_relu(nn_list):
            # There are no more neurons and no more layers
            new_target = None

        else:
            # There is another ReLU layer: propagate the star to that layer and reset the neuron
            star = propagate_until_relu(star, nn_list, True)
            star.ref_neuron = 0
            next_layer = star.ref_layer
            new_target = RefinementTarget(next_layer, 0)

    return new_target, star


# TODO Deprecated
def get_target_sequential_OLD(star: Star, current_target: RefinementTarget, nn_list: list) -> (RefinementTarget, Star):
    """
    This function updates the target for the refinement of the star using
    a sequential approach. For each ReLU layer all neurons are refined
    sequentially.

    Parameters
    ----------
    star : Star
        The star to refine
    current_target : RefinementTarget
        The current target to update
    nn_list : list
        The list of the network layers

    Returns
    ----------
    tuple, Star
        The new target for the refinement, it is None when there is no more
        refinement to do for this star, and the propagated star

    """

    def get_last_relu(net_list: list):
        last_relu_idx = 0
        for net_layer in net_list[::-1]:
            if isinstance(net_layer, nodes.ReLUNode):
                last_relu_idx = net_list.index(net_layer)
                break

        return last_relu_idx

    new_target = None

    # Propagate current star to the next ReLU layer
    star = propagate_until_relu(star, nn_list)
    target_layer = star.ref_layer

    # Check if the target refers to a previous layer
    if target_layer != current_target.layer_idx and target_layer < get_last_relu(nn_list):
        new_target = RefinementTarget(target_layer, 0)

    # Check if the neurons in the layer have been all processed
    elif current_target.neuron_idx == star.center.shape[0] - 1:

        # Check if all the layers have been processed
        if target_layer < get_last_relu(nn_list):

            # Go to the first neuron of next ReLU layer
            next_relu = target_layer
            for layer in nn_list[target_layer + 1:]:
                if isinstance(layer, nodes.ReLUNode):
                    next_relu = nn_list.index(layer)
                    break

            new_target = RefinementTarget(next_relu, 0)
            star.ref_layer += 1
            star = propagate_until_relu(star, nn_list)
    else:
        # Increment the neuron
        new_target = RefinementTarget(target_layer, current_target.neuron_idx + 1)

    return new_target, star


def split_star(star: Star, target: RefinementTarget, nn_list: list, bounds_dict: dict) -> list:
    """
    For a star we only need the var_index to target a specific neuron.
    The index relative to this neuron is determined by the heuristic that
    also takes into account what layer the star comes from.

    When splitting I also need to update the bounds and return them

    Parameters
    ----------
    star : Star
        The star object to split
    target : RefinementTarget
        The target layer and neuron to refine
    nn_list : list
        The neural network as a list of layers
    bounds_dict : dict
        The bounds of the network layers

    Returns
    ----------
    list
        A list of one or two 'Star' elements, depending on the stability
        of the current neuron

    """

    index = target.neuron_idx

    mask = np.identity(star.center.shape[0])
    mask[index, index] = 0

    cur_bounds = bounds_dict[nn_list[star.ref_layer].identifier]
    stable = abst.check_stable(index, cur_bounds)

    # Positive stable
    if stable == 1:
        star.ref_layer = target.layer_idx
        star.ref_neuron += 1
        return [(star, bounds_dict)]

    # Negative stable
    elif stable == -1:
        new_c = np.matmul(mask, star.center)
        new_b = np.matmul(mask, star.basis_matrix)
        new_pred = star.predicate_matrix
        new_bias = star.predicate_bias
        new_star = Star(new_pred, new_bias, new_c, new_b)

        new_star.ref_layer = target.layer_idx
        new_star.ref_neuron = star.ref_neuron + 1

        return [(new_star, bounds_dict)]

    # Unstable
    else:
        # Lower star
        lower_c = np.matmul(mask, star.center)
        lower_b = np.matmul(mask, star.basis_matrix)
        lower_pred = np.vstack((star.predicate_matrix, star.basis_matrix[index, :]))
        lower_bias = np.vstack((star.predicate_bias, -star.center[index]))
        lower_star = Star(lower_pred, lower_bias, lower_c, lower_b)

        lower_star.ref_layer = target.layer_idx
        lower_star.ref_neuron = star.ref_neuron + 1

        # Upper star
        upper_c = star.center
        upper_b = star.basis_matrix
        upper_pred = np.vstack((star.predicate_matrix, -star.basis_matrix[index, :]))
        upper_bias = np.vstack((star.predicate_bias, star.center[index]))
        upper_star = Star(upper_pred, upper_bias, upper_c, upper_b)

        upper_star.ref_layer = target.layer_idx
        upper_star.ref_neuron = star.ref_neuron + 1

        # TODO update bounds
        return [
            (lower_star, bounds_dict),
            (upper_star, bounds_dict)
        ]


def get_counterexample(unsafe_stars: list, prop: 'NeverProperty') -> Tensor:
    """
    This function is used to extract a counterexample from a star.
    The counterexample that we are interested into is the witness, i.e.,
    the input assignment that resulted in an intersection.

    Parameters
    ----------
    unsafe_stars : list
        Unsafe stars in output
    prop : NeverProperty
        The property of interest

    Returns
    ----------
    Tensor
        The counterexample input Tensor

    """

    # Extract counterexample stars
    counterexample_stars = []

    for unsafe_star in unsafe_stars:
        temp_star = abst.Star(prop.in_coef_mat, prop.in_bias_mat)
        temp_star.predicate_matrix = copy.deepcopy(unsafe_star.predicate_matrix)
        temp_star.predicate_bias = copy.deepcopy(unsafe_star.predicate_bias)
        counterexample_stars.append(temp_star)

    return counterexample_stars[0].get_samples(num_samples=1)[0]
