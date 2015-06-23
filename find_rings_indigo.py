#!/usr/bin/env python
# author          : Pavel
# date            : 18.06.15
# version         : 0.1
# python_version  : 3
# copyright       : Pavel 2015
# license         : GPL3
#==============================================================================

import os
import argparse

from indigo import Indigo, IndigoException


indigo = Indigo()


def main_params(in_sdf, out_txt, verbose, error_mol):

    if error_mol:
        error_log_file = os.path.join(os.path.dirname(out_txt), 'indigo_errors.log')
        if os.path.isfile(error_log_file):
            os.remove(error_log_file)

    with open(out_txt, "wt") as f:

        for mol in indigo.iterateSDFile(in_sdf):

            try:

                mol.dearomatize()  # in order to avoid different aromatic forms in different molecules
                mol_name = mol.name()
                if verbose:
                    print("Searching for rings in", mol_name)

                # return all rings in format [[SMILES, {indices}], ...]
                rings = [[ring.clone().canonicalSmiles().split(" ")[0], set([atom.index() for atom in ring.iterateAtoms()])] for ring in mol.iterateRings(1, mol.countAtoms())]
                rings = sorted(rings, key=lambda x: len(x[1]), reverse=True)

                for i, r in enumerate(rings):
                    # if ring is not present in a bigger one than add it to the output text file
                    if all([not r[1].issubset(rings[j][1]) for j in range(i-1)]):
                        # create 1-based indices
                        tmp_ids = list(map(lambda x: x + 1, r[1]))
                        f.write(mol_name + "\t" + r[0] + "\t" + "\t".join(map(str, tmp_ids)) + "\n")

            except IndigoException as e:

                print('%s was skipped due to error' % mol.name())
                print(e)

                if error_mol:
                    with open(error_log_file, 'at') as f_err:
                        f_err.write('%s\t%s\n' % (mol.name(), e))


def main():

    parser = argparse.ArgumentParser(description='Find indices of rings atoms in molecules from input sdf-file.')
    parser.add_argument('-i', '--in', metavar='input.sdf', required=True,
                        help='input sdf file with standardized structures, molecules should have titles.')
    parser.add_argument('-o', '--out', metavar='output.txt', required=True,
                        help='output text file; each line contains tab-separated fields: name of a molecule, '
                             'name of a fragment and list of corresponding atom numbers.')
    parser.add_argument('-v', '--verbose', action='store_true', default=False,
                        help='show progress on the screen.')
    parser.add_argument('-e', '--error_mol', action='store_true', default=True,
                        help='save molecules which cause error to a text log file named indigo_errors.log.')

    args = vars(parser.parse_args())
    for o, v in args.items():
        if o == "in": in_sdf = v
        if o == "out": out_txt = v
        if o == "verbose": verbose = v
        if o == "error_mol": error_mol = v

    main_params(in_sdf, out_txt, verbose, error_mol)


if __name__ == '__main__':
    main()