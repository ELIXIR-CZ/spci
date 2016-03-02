#!/usr/bin/env python
#==============================================================================
# author          : Pavel Polishchuk
# date            : 01-11-2014
# version         : 0.1
# python_version  : 3.2
# copyright       : Pavel Polishchuk 2014
# license         : GPL3
#==============================================================================

import os
from runpy import run_path
import sys
import ast
import glob
import shutil
import tkinter as tk

from tkinter import ttk
from tkinter import filedialog
from tkinter import messagebox
from tkinter import font as tkfont
from tkinter import messagebox
from multiprocessing import cpu_count
from subprocess import call
from collections import OrderedDict

import sdf_field2title
import calc_atomic_properties_chemaxon
import model
import find_frags_indigo as find_frags
import find_rings_indigo as find_rings
import find_murcko_indigo as find_murcko
import find_frags_auto_indigo as find_frags_auto
import calc_frag_contrib
import plot_contributions
import extractsdf
import filter_descriptors

sys.path.insert(1, os.path.join(sys.path[0], 'sirms'))
import sirms


def get_script_path():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


class StatWindow(tk.Toplevel):

# it's a magic
# ideas were taken from
# http://stackoverflow.com/questions/13205727/using-ttk-treeview-how-can-i-get-horizontal-scrolling-to-work-as-expected

    def close_window(self):
        self.destroy()

    def __read_stat_file(self, stat_fname, keep_only_important_details=True):

        d = dict()
        with open(stat_fname) as f:
            d['model_type'] = f.readline().strip()
            d['header'] = f.readline().strip().split('\t')
            d['lines'] = []
            for line in f:
                d['lines'].append(line.strip().split('\t'))

        if keep_only_important_details:
            for i, line in enumerate(d['lines']):
                if line[1] == 'gbm':
                    names = ['subsample', 'learning_rate', 'n_estimators', 'max_features', 'max_depth']
                if line[1] == 'rf':
                    names = ['n_estimators', 'max_features']
                if line[1] == 'svm':
                    names = ['kernel', 'C', 'gamma']
                if line[1] == 'knn':
                    names = ['n_neighbors']
                if line[1] == 'pls':
                    names = ['n_components']
                tmp = ast.literal_eval('{' + line[-1] + '}')
                d['lines'][i][-1] = '; '.join([k + ' = ' + str(v) for k, v in tmp.items() if k in names])

        return d

    def fill_data(self, stat_fname):

        d = self.__read_stat_file(stat_fname)

        self.title(d['model_type'] + ' models statistics')

        self.tree.configure(columns=d['header'], show="headings")
        for col in d['header']:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=tkfont.Font().measure(col), stretch=False)
        self.tree.column(d['header'][-1], stretch=True)

        for item in d['lines']:
            self.tree.insert('', 'end', values=item)
            for ix, val in enumerate(item):
                col_w = tkfont.Font().measure(val)
                if self.tree.column(d['header'][ix], width=None) < col_w:
                    self.tree.column(d['header'][ix], width=col_w)

        # resize window
        self.configure(height=len(d['lines']) * 40 + 60)

    def __init__(self, parent):
        tk.Toplevel.__init__(self, parent, width=600)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.treeFrame = ttk.Frame(self)
        self.treeFrame.grid(row=0, column=0, padx=5, pady=5, sticky='nsew')
        self.treeFrame.grid_columnconfigure(0, weight=1)
        self.treeFrame.rowconfigure(0, weight=1)

        def autoscrollv(sbar, first, last):
            first, last = float(first), float(last)
            if first <= 0 and last >= 1:
                sbar.grid_remove()
            else:
                sbar.grid()
            sbar.set(first, last)

        def autoscrollh(sbar, first, last):
            first, last = float(first), float(last)
            if first <= 0 and last >= 1:
                sbar.grid_remove()
            else:
                sbar.grid()
            sbar.set(first, last)

        vsb = ttk.Scrollbar(self.treeFrame, orient="vertical")
        hsb = ttk.Scrollbar(self.treeFrame, orient="horizontal")

        self.tree = ttk.Treeview(self.treeFrame, height=10,
                                 yscrollcommand=lambda f, l: autoscrollv(vsb, f, l),
                                 xscrollcommand=lambda f, l: autoscrollh(hsb, f, l))
        self.tree.column("#0", minwidth=400, stretch=True)

        vsb['command'] = self.tree.yview
        hsb['command'] = self.tree.xview

        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(column=1, row=0, sticky='ns')
        hsb.grid(column=0, row=1, sticky='ew')

        ttk.Button(self.treeFrame, text='OK', command=self.close_window).grid(column=0, row=2)

        self.grid_propagate(False)
        self.configure(width=600, height=150)


class SpinboxCPUFrame(ttk.Labelframe):

    def __init__(self, parent, column, row, name="Number of cores to use"):

        ttk.Labelframe.__init__(self, parent, text=name)
        self.grid(column=column, row=row, columnspan=10, sticky=(tk.W, tk.E), padx=5, pady=5)

        self._value = tk.StringVar(value=str(cpu_count()-1))
        tk.Spinbox(self, from_=1, to=cpu_count(), textvariable=self._value, width=5).grid(column=0, row=2, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))

    def get_value(self):
        return int(self._value.get())


class ModelsFrame(ttk.Labelframe):

    def __init__(self, parent, name, column, row, full_version=True):

        ttk.Labelframe.__init__(self, parent, text=name)
        self.grid(column=column, row=row, columnspan=10, sticky=(tk.W, tk.E), padx=5, pady=5)

        self._full_version = full_version

        self.model_type = tk.StringVar(value='reg')

        self.model_rf = tk.BooleanVar(value=True)
        self.model_svm = tk.BooleanVar(value=True)
        self.model_gbm = tk.BooleanVar(value=True)
        self.model_pls = tk.BooleanVar(value=True)
        self.model_knn = tk.BooleanVar(value=False)

        self.model_rf_class = tk.BooleanVar(value=True)
        self.model_svm_class = tk.BooleanVar(value=True)
        self.model_gbm_class = tk.BooleanVar(value=True)
        self.model_knn_class = tk.BooleanVar(value=False)

        ttk.Radiobutton(self, text='Regression (RF, GBM, SVM, PLS)', name='model_type_reg', value='reg', variable=self.model_type).grid(column=0, row=0, sticky=(tk.W), padx=5, pady=5)
        ttk.Radiobutton(self, text='Binary classification (0-1) (RF, GBM, SVM)', name='model_type_class', value='class', variable=self.model_type).grid(column=1, row=0, sticky=(tk.W), padx=5, pady=5)

        if self._full_version:

            ttk.Checkbutton(self, variable=self.model_rf, name='chk_rf', text='Random Forest (RF)', command=self.reg_model_checked).grid(column=0, row=1, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_svm, name='chk_svr', text='Support vector regression (SVR)', command=self.reg_model_checked).grid(column=0, row=2, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_gbm, name='chk_gbm', text='Gradient boosting regression (GBR)', command=self.reg_model_checked).grid(column=0, row=3, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_pls, name='chk_pls', text='Partial least squares (PLS)', command=self.reg_model_checked).grid(column=0, row=4, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_knn, name='chk_knn', text='k-Nearest neighbors (kNN)', command=self.reg_model_checked).grid(column=0, row=5, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))

            ttk.Checkbutton(self, variable=self.model_rf_class, name='chk_rf_class', text='Random Forest (RF)', command=self.class_model_checked).grid(column=1, row=1, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_svm_class, name='chk_svr_class', text='Support vector classification (SVC)', command=self.class_model_checked).grid(column=1, row=2, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_gbm_class, name='chk_gbm_class', text='Gradient boosting classification (GBC)', command=self.class_model_checked).grid(column=1, row=3, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))
            ttk.Checkbutton(self, variable=self.model_knn_class, name='chk_knn_class', text='k-Nearest neighbors (kNN)', command=self.class_model_checked).grid(column=1, row=4, sticky=(tk.W, tk.E), padx=5, pady=(1, 0))

        self.columnconfigure(0, pad=80)

    def class_model_checked(self):
        self.model_type.set(value='class')
        # self.children['model_type_class'].set(value=True)

    def reg_model_checked(self):
        self.model_type.set(value='reg')
        # self.children['model_type_reg'].set(value=True)

    def get_selected_models(self):

        output = []
        if self.model_type.get() == 'reg':
            if self._full_version:
                if self.model_gbm.get(): output.append('gbm')
                if self.model_rf.get(): output.append('rf')
                if self.model_svm.get(): output.append('svm')
                if self.model_pls.get(): output.append('pls')
                if self.model_knn.get(): output.append('knn')
            else:
                output = ['gbm', 'rf', 'svm', 'pls']
        if self.model_type.get() == 'class':
            if self._full_version:
                if self.model_gbm_class.get(): output.append('gbm')
                if self.model_rf_class.get(): output.append('rf')
                if self.model_svm_class.get(): output.append('svm')
                if self.model_knn_class.get(): output.append('knn')
            else:
                output = ['gbm', 'rf', 'svm']

        return output

    def get_selected_models_with_type(self):
        models = self.get_selected_models()
        return [m + '_' + self.model_type.get() for m in models]


class Tab_1(ttk.Frame):

    def __select_chemaxon_dir(self):
        self.chemaxon_dir.set(filedialog.askdirectory())

    def __select_sdf_path(self):
        self.sdf_path.set(filedialog.askopenfilename(filetypes=[('SDF files', '*.sdf')]))

    def __select_property_file_path(self):
        self.property_file_path.set(filedialog.askopenfilename(filetypes=[('Property text file', '*.txt')],
                                                               initialdir=os.path.dirname(self.sdf_path.get())))

    def __remove_forbidden_y(self, filename):
        # remove non-numeric items from y file (with compounds properties)

        def is_number(s):
            try:
                float(s)
                return True
            except ValueError:
                return False

        lines = open(filename).readlines()
        # add header to the output
        output = [lines[0]]
        for line in lines[1:]:
            if is_number(line.strip().split('\t')[1]):
                output.append(line)
        open(filename, 'wt').writelines(output)

    def __build_models(self):

        if self.sdf_path.get() == '':
            messagebox.showerror('ERROR!', 'Specify sdf filename and path.')
            return

        # if x.txt does not exist then do all standardization and descriptors calculation
        if not os.path.isfile(os.path.join(os.path.dirname(self.sdf_path.get()), 'x.txt')):

            # process mol title
            if self.compound_names.get() == 'title':
                tmp_sdf = None
            else:
                tmp_sdf = self.sdf_path.get().rsplit('.', 1)[0] + '_titles.sdf'
                if self.compound_names.get() == 'gen':
                    sdf_field2title.main_params(self.sdf_path.get(), None, tmp_sdf)
                elif self.compound_names.get() == 'field':
                    sdf_field2title.main_params(self.sdf_path.get(), self.sdf_id_field_name.get().strip(), tmp_sdf)

            input_sdf = self.sdf_path.get() if tmp_sdf is None else tmp_sdf

            # standardization and property labeling
            if self.chemaxon_usage.get() == 'with_chemaxon':

                # standardize
                print('Standardization is in progress...')
                # copy xml-rules if the file is absent in the sdf folder
                shutil.copyfile(os.path.join(get_script_path(), 'std_rules.xml'),
                                os.path.join(os.path.dirname(self.sdf_path.get()), 'std_rules.xml'))
                # run standardize
                std_sdf_tmp = input_sdf + '.std.sdf'
                run_params = ['standardize',
                              '-c',
                              os.path.join(os.path.dirname(self.sdf_path.get()), 'std_rules.xml'),
                              input_sdf,
                              '-f',
                              'sdf',
                              '-o',
                              std_sdf_tmp]
                call(' '.join(run_params), shell=True)

                # calc atomic properties with Chemaxon
                print('Atomic properties calculation is in progress...')
                # input_sdf = self.sdf_path.get() if tmp_sdf is None else tmp_sdf
                output_sdf = self.sdf_path.get().rsplit(".")[0] + '_std_lbl.sdf'
                calc_atomic_properties_chemaxon.main_params(std_sdf_tmp,
                                                            output_sdf,
                                                            ['charge', 'logp', 'acc', 'don', 'refractivity'],
                                                            None,
                                                            os.path.join(self.chemaxon_dir.get(), 'cxcalc'))

                os.remove(std_sdf_tmp)
                if tmp_sdf is not None:
                    os.remove(tmp_sdf)

            else:

                output_sdf = self.sdf_path.get().rsplit(".")[0] + '_std_lbl.sdf'
                if os.path.isfile(output_sdf):
                    os.remove(output_sdf)
                os.rename(tmp_sdf, output_sdf)

            # copy setup.txt to folder with sdf file
            shutil.copyfile(os.path.join(get_script_path(), 'setup.txt'),
                            os.path.join(os.path.dirname(self.sdf_path.get()), 'setup.txt'))

            # calc sirms descriptors
            if self.chemaxon_usage.get() == 'with_chemaxon':
                atom_diff = ['CHARGE', 'LOGP', 'HB', 'REFRACTIVITY']
            else:
                atom_diff = ['elm']
            x_fname = os.path.join(os.path.dirname(output_sdf), 'x.txt')
            sirms.main_params(in_fname=output_sdf,
                              out_fname=x_fname,
                              opt_no_dict=False,
                              opt_diff=atom_diff,
                              opt_types=list(range(3, 12)),
                              mix_fname=None,
                              opt_mix_ordered=None,
                              opt_ncores=1,
                              opt_verbose=True,
                              opt_noH=True,
                              frag_fname=None,
                              parse_stereo=False,
                              output_format='svm',
                              quasimix=False,
                              id_field_name=None)

            # filter sirms descriptors
            filter_descriptors.main_params(in_fname=x_fname,
                                           out_fname=x_fname,
                                           file_format='svm')

        else:
            x_fname = os.path.join(os.path.dirname(self.sdf_path.get()), 'x.txt')
            self.property_file_path.set(os.path.join(os.path.dirname(self.sdf_path.get()),
                                                     self.property_field_name.get().strip() + '.txt'))

        # extract property, check for numeric values and save to separate file
        if self.property_field_name.get() != '':
            property_filename = os.path.join(os.path.dirname(self.sdf_path.get()),
                                             self.property_field_name.get().strip() + '.txt')
            extractsdf.main_params(in_fname=os.path.splitext(self.sdf_path.get())[0] + '_std_lbl.sdf',
                                   out_fname=property_filename,
                                   title=True,
                                   field_names=[self.property_field_name.get().strip()],
                                   all_fields=False)
            self.__remove_forbidden_y(property_filename)
            self.property_file_path.set(property_filename)

        # remove models from output dir which conflict with newly build models
        models_dir = os.path.join(os.path.dirname(x_fname), self.property_field_name.get().strip(), "models")
        if os.path.isdir(models_dir):
            file_names = glob.glob1(models_dir, '*.pkl')
            for file_name in file_names:
                if file_name.rsplit('.', 1)[0] in self.models_frame.get_selected_models():
                    os.remove(os.path.join(models_dir, file_name))

        # build models
        model.main_params(x_fname=x_fname,
                          y_fname=self.property_file_path.get(),
                          model_names=self.models_frame.get_selected_models(),
                          models_dir=models_dir,
                          ncores=self.sb_cpu_count.get_value(),
                          # ncores=max(1, cpu_count() - 1),
                          model_type=self.models_frame.model_type.get(),
                          verbose=1,
                          cv_predictions=True,
                          input_format='svm')

        # update list of models to plot
        self.master.children['tab_3']._show_models_list()

    def __show_models_stat(self):
        win = StatWindow(self)
        win.fill_data(os.path.join(os.path.dirname(self.sdf_path.get()),
                                   self.property_field_name.get().strip(),
                                   'models\\models_stat.txt'))

    def __add_sdf_path_to_history(self, sdf_path):
        if sdf_path is None or sdf_path == "":
            return None
        max_lines = 10
        new_line = sdf_path + '\n'
        hist = os.path.join(get_script_path(), 'history.txt')
        if os.path.isfile(hist):
            lines = open(hist).readlines()
            # remove newly added line if it is present in lines
            if new_line in lines:
                lines.remove(new_line)
            # keep only allowed number of lines - 1
            if len(lines) >= max_lines:
                lines = lines[-(max_lines-1):]
            lines.append(new_line)
            open(hist, 'wt').writelines(lines)
        else:
            open(hist, 'wt').write(new_line)

    def __read_sdf_history(self):
        file_name = os.path.join(get_script_path(), 'history.txt')
        if os.path.isfile(file_name):
            lines = open(file_name).readlines()
            lines = [line.strip() for line in lines]
            lines.reverse()
            return lines

    def __sdf_path_changed(self, varname, elementname, mode):
        field_names = self.__read_sdf_field_names(self.sdf_path.get())
        if field_names:
            self.children['sdf_label_frame'].children['property_field_name'].configure(values=field_names)
            self.children['sdf_label_frame'].children['property_field_name'].set(value=field_names[0])
            self.children['optional_label_frame'].children['inner_frame'].children['sdf_id_field_name'].configure(values=field_names)
            self.children['optional_label_frame'].children['inner_frame'].children['sdf_id_field_name'].set(value=field_names[0])
        self.__add_sdf_path_to_history(self.sdf_path.get())
        self.children['sdf_label_frame'].children['sdf_path_combobox'].configure(values=self.__read_sdf_history())
        # update list of models to plot
        self.master.children['tab_3']._show_models_list()

    def __prop_field_name_changed(self, varname, elementname, mode):
        # update list of models to plot
        self.master.children['tab_3']._show_models_list()

    def __read_sdf_field_names(self, fname):
        field_names = []
        if not os.path.isfile(fname):
            messagebox.showerror('ERROR!', "Specified file name doesn't exist.")
            return field_names
        with open(fname) as f:
            line = f.readline().rstrip()
            while line != '$$$$':
                # one or two spaces between > and < can be possible
                if line.startswith('>  <') and line.endswith('>'):
                    field_names.append(line[4:-1])
                if line.startswith('> <') and line.endswith('>'):
                    field_names.append(line[3:-1])
                line = f.readline().rstrip()
        return field_names

    def __set_compound_names_choice_event(self, event):
        self.compound_names.set(value='field')

    def __chemaxon_usage_changed(self, varname, elementname, mode):
        contr_names = ['contr_overall', 'contr_charge', 'contr_logp', 'contr_hb', 'contr_ref']
        if self.chemaxon_usage.get() == 'with_chemaxon':
            states = dict(zip(contr_names, ['normal'] * len(contr_names)))
        else:
            states = dict(zip(contr_names, ['normal', 'disabled', 'disabled', 'disabled', 'disabled']))
            # uncheck all except overall
            self.master.children['tab_3'].contr_charge.set(False)
            self.master.children['tab_3'].contr_logp.set(False)
            self.master.children['tab_3'].contr_hb.set(False)
            self.master.children['tab_3'].contr_ref.set(False)

        for contr_name in contr_names:
            self.master.children['tab_3'].children['contributions'].children[contr_name].config(state=states[contr_name])

    def __init__(self, parent, tab_name):

        ttk.Frame.__init__(self, parent, name='tab_1')

        self.chemaxon_usage = tk.StringVar(value='with_chemaxon')
        self.chemaxon_dir = tk.StringVar()
        self.sdf_path = tk.StringVar()
        self.property_file_path = tk.StringVar()
        self.sdf_id_field_name = tk.StringVar()
        self.property_field_name = tk.StringVar()
        self.compound_names = tk.StringVar(value='gen')

        chemaxon_frame = ttk.Labelframe(self, text='Structural/physico-chemical interpretation', name='chemaxon_frame')
        chemaxon_frame.grid(column=0, row=0, sticky=(tk.E, tk.W), columnspan=4, padx=5, pady=5)
        ttk.Radiobutton(chemaxon_frame, text='Structural & functional (Chemaxon required)', variable=self.chemaxon_usage, value='with_chemaxon').grid(column=0, row=0, sticky=(tk.W), padx=5, pady=1)
        ttk.Radiobutton(chemaxon_frame, text='Structural only (no Chemaxon usage)', variable=self.chemaxon_usage, value='no_chemaxon').grid(column=0, row=1, sticky=(tk.W), padx=5, pady=1)
        # ttk.Label(self, text='Optional. Path to cxcalc utility folder, '
        #                      'e.g. C:\\Program Files (x86)\\Chemaxon\\JChem\\bin').grid(column=0, row=0, sticky=(tk.W))
        # ttk.Entry(self, width=70, textvariable=self.chemaxon_dir).grid(column=0, row=1, sticky=(tk.W, tk.E))
        # ttk.Button(self, text='Browse...', command=self.__select_chemaxon_dir).grid(column=1, row=1, sticky=(tk.W))
        # ttk.Button(self, text='Auto-detect').grid(column=2, row=1, sticky=(tk.W))

        frame = ttk.Labelframe(self, text='SDF with compounds', name='sdf_label_frame')
        frame.grid(column=0, row=2, sticky=(tk.E, tk.W), columnspan=4, padx=5, pady=5)
        ttk.Label(frame, text='Path to SDF-file').grid(column=0, row=2, sticky=(tk.W, tk.S), padx=5)
        ttk.Label(frame, text='property field name').grid(column=2, row=2, sticky=(tk.W), padx=5)
        # ttk.Entry(frame, width=70, textvariable=self.sdf_path).grid(column=0, row=3, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        ttk.Combobox(frame, name='sdf_path_combobox', width=70, textvariable=self.sdf_path, values=self.__read_sdf_history()).grid(column=0, row=3, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        ttk.Button(frame, text='Browse...', command=self.__select_sdf_path).grid(column=1, row=3, sticky=(tk.W), padx=5, pady=(0, 5))
        ttk.Combobox(frame, name='property_field_name', width=20, textvariable=self.property_field_name, state='readonly').grid(column=2, row=3, sticky=(tk.W), padx=5, pady=(0, 5))

        frame = ttk.Labelframe(self, text='Optional. Compound names. External text file with compound property values', name='optional_label_frame')
        frame.grid(column=0, row=4, sticky=(tk.E, tk.W), columnspan=4, padx=5, pady=5)

        ttk.Radiobutton(frame, text='Automatically generate compound names', variable=self.compound_names, value='gen').grid(column=0, row=0, sticky=(tk.W), padx=5, pady=1)
        ttk.Radiobutton(frame, text='Use compound titles from SDF file', variable=self.compound_names, value='title').grid(column=0, row=1, sticky=(tk.W), padx=5, pady=1)

        inner_frame = ttk.Frame(frame, name='inner_frame')
        inner_frame.grid(column=0, row=3, columnspan=4, sticky=(tk.W, tk.E))
        ttk.Radiobutton(inner_frame, text='Use field values as compound names from SDF file', variable=self.compound_names, value='field').grid(column=0, row=3, sticky=(tk.W), padx=5, pady=1)
        cmbbox = ttk.Combobox(inner_frame, name='sdf_id_field_name', width=20, textvariable=self.sdf_id_field_name, state='readonly')
        cmbbox.grid(column=1, row=3, sticky=(tk.W), padx=5, pady=1)
        cmbbox.bind('<<ComboboxSelected>>', self.__set_compound_names_choice_event)
        # ttk.Entry(inner_frame, width=20, textvariable=self.sdf_id_field_name).grid(column=1, row=3, sticky=(tk.W), padx=5, pady=1)

        ttk.Label(frame, text='Path to text file with property values').grid(column=0, row=5, sticky=(tk.W), padx=5, pady=(15, 0))
        ttk.Entry(frame, width=70, textvariable=self.property_file_path).grid(column=0, row=7, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))
        ttk.Button(frame, text='Browse...', command=self.__select_property_file_path).grid(column=1, row=7, sticky=(tk.W), padx=5, pady=(0, 5))

        self.models_frame = ModelsFrame(self, 'Models', 0, 10, True)

        self.sb_cpu_count = SpinboxCPUFrame(self, 0, 12)

        buttons_frame = ttk.Frame(self)
        buttons_frame.grid(column=0, row=20, columnspan=3, sticky=(tk.W, tk.E))

        ttk.Button(buttons_frame, text='Build models', command=self.__build_models).grid(column=0, row=0, sticky=(tk.E))
        ttk.Button(buttons_frame, text='Show statistics', command=self.__show_models_stat).grid(column=1, row=0, sticky=(tk.W))

        buttons_frame.columnconfigure(0, weight=1)
        buttons_frame.columnconfigure(1, weight=1)

        self.columnconfigure(0, weight=1)

        self.sdf_path.trace('w', self.__sdf_path_changed)
        self.property_field_name.trace('w', self.__prop_field_name_changed)
        self.chemaxon_usage.trace('w', self.__chemaxon_usage_changed)

        parent.add(self, text=tab_name)


class Tab_2(ttk.Frame):

    def get_frag_prefix(self):
        if self.frags_choice.get() != 'auto':
            return self.frags_choice.get()
        else:
            return self.auto_frags_choice.get().split(':')[0]

    def __select_user_frags(self):
        self.user_frags_path.set(filedialog.askopenfilename(filetypes=[('SMARTS file', '*.smarts; *.txt'),
                                                                       ('SMILES file', '*.smi; *.smiles'),
                                                                       ('SDF file', '*.sdf'),
                                                                       ('All files', '*.*')],
                                                            initialdir=os.path.dirname(self.master.children['tab_1'].sdf_path.get())))

    def __calc_contributions(self):

        """
        Intermediate files with atom ids and descriptors of fragmented molecules are stored in main dir for all
        pre-defined fragmentation schemes. Intermediate files generated during user-defined scheme are stored in
        the work (property) dir.
        Files with calculated contributions are stored in work (property) dir.
        """

        sdf_fname = self.master.children['tab_1'].sdf_path.get()[:-4] + '_std_lbl.sdf'

        prop_name = self.master.children['tab_1'].property_field_name.get()
        main_dir = os.path.dirname(sdf_fname)
        wd = os.path.realpath(os.path.join(main_dir, prop_name))

        # check for existence of XXX_frag_x.txt to avoid recalculation of fragments and descriptors
        if self.frags_choice.get() == 'user' and os.path.isfile(os.path.join(wd, 'user_frag_x.txt')):
            exist = messagebox.askyesnocancel(message='Do you want to keep existed user-defined fragmentation?', icon='question', default='yes')
            if exist is None:
                return
        else:
            exist = os.path.isfile(os.path.join(main_dir, self.get_frag_prefix() + '_frag_x.txt'))

        if not exist:

            if self.frags_choice.get() == 'user':
                ids_fname = os.path.join(wd, self.get_frag_prefix() + '_frag_ids.txt')
            else:
                ids_fname = os.path.join(main_dir, self.get_frag_prefix() + '_frag_ids.txt')

            if self.frags_choice.get() == 'user':
                if self.user_frags_path.get() == '':
                    messagebox.showerror('Error!', 'Specify path to the fragments file.')
                    return
                else:
                    frag_fname = self.user_frags_path.get()
            elif self.frags_choice.get() == 'default':
                frag_fname = os.path.join(get_script_path(), 'default.smarts')

            # find atom ids
            if self.frags_choice.get() in ['user', 'default']:
                find_frags.main_params(in_sdf=sdf_fname,
                                       out_txt=ids_fname,
                                       in_frags=frag_fname,
                                       remove_all=False,
                                       verbose=True,
                                       error_fname=os.path.join(main_dir, "indigo_errors.log"))
            elif self.frags_choice.get() == 'rings':
                find_rings.main_params(in_sdf=sdf_fname,
                                       out_txt=ids_fname,
                                       verbose=True,
                                       error_fname=os.path.join(main_dir, "indigo_errors.log"))
            elif self.frags_choice.get() == 'murcko':
                find_murcko.main_params(in_sdf=sdf_fname,
                                        out_txt=ids_fname,
                                        verbose=True,
                                        error_fname=os.path.join(main_dir, "indigo_errors.log"))
            elif self.frags_choice.get() == 'auto':
                find_frags_auto.main_params(in_sdf=sdf_fname,
                                            out_txt=ids_fname,
                                            query=self.auto_schemes[self.auto_frags_choice.get()],
                                            max_cuts=3,
                                            verbose=True,
                                            error_fname=os.path.join(main_dir, "indigo_errors.log"))

            # calc sirms descriptors
            if self.master.children['tab_1'].chemaxon_usage.get() == 'with_chemaxon':
                atom_diff = ['CHARGE', 'LOGP', 'HB', 'REFRACTIVITY']
            else:
                atom_diff = ['elm']

            if self.frags_choice.get() == 'user':
                x_fname = os.path.join(wd, self.get_frag_prefix() + '_frag_x.txt')
            else:
                x_fname = os.path.join(main_dir, self.get_frag_prefix() + '_frag_x.txt')

            sirms.main_params(in_fname=sdf_fname,
                              out_fname=x_fname,
                              opt_no_dict=False,
                              opt_diff=atom_diff,
                              opt_types=list(range(3, 12)),
                              mix_fname=None,
                              opt_mix_ordered=None,
                              opt_ncores=1,
                              opt_verbose=True,
                              opt_noH=True,
                              frag_fname=ids_fname,
                              parse_stereo=False,
                              output_format='svm',
                              quasimix=False,
                              id_field_name=None)

            # filter sirms descriptors
            filter_descriptors.main_params(in_fname=x_fname,
                                           out_fname=x_fname,
                                           file_format='svm')
        else:

            # define path to descriptors of fragmented structures
            if self.frags_choice.get() == 'user':
                x_fname = os.path.join(wd, self.get_frag_prefix() + '_frag_x.txt')
            else:
                x_fname = os.path.join(main_dir, self.get_frag_prefix() + '_frag_x.txt')

        # calc contributions
        out_fname = os.path.join(wd, self.get_frag_prefix() + '_frag_contributions.txt')
        models = self.master.children['tab_1'].models_frame.get_selected_models()
        model_dir = os.path.join(wd, 'models')

        if self.master.children['tab_1'].chemaxon_usage.get() == 'with_chemaxon':
            prop_name = ['overall', 'CHARGE', 'LOGP', 'HB', 'REFRACTIVITY']
        else:
            prop_name = ['overall']

        calc_frag_contrib.main_params(x_fname=x_fname,
                                      out_fname=out_fname,
                                      model_names=models,
                                      model_dir=model_dir,
                                      prop_names=prop_name,
                                      model_type=self.master.children['tab_1'].models_frame.model_type.get(),
                                      verbose=True,
                                      save_pred=True,
                                      input_format='svm',
                                      long_format=False)

        print("Calculation completed.")

    def __change_to_user(self, event):
        self.frags_choice.set(value='user')

    def __change_to_auto(self, event):
        self.frags_choice.set(value='auto')

    def __run_calc_contrib(self, event):
        self.__calc_contributions()

    def __init__(self, parent, tab_name):

        ttk.Frame.__init__(self, parent, name='tab_2')

        self.auto_schemes = OrderedDict()
        self.auto_schemes['auto1: [#6+0;!$(*=,#[!#6])]!@!=!#[*] (MMP like, quite exhaustive)'] = '[#6+0;!$(*=,#[!#6])]!@!=!#[*]'
        self.auto_schemes['auto2: [R]-[!R] (break bond between chain and ring atoms)'] = '[R]-[!R]'

        self.frags_choice = tk.StringVar(value='default')
        self.auto_frags_choice = tk.StringVar(value=list(self.auto_schemes.keys())[0])
        self.user_frags_path = tk.StringVar()

        frame = ttk.Labelframe(self, text='Select fragments set or fragmentation scheme')
        frame.grid(column=0, row=0, columnspan=3, sticky=(tk.E, tk.W), padx=5, pady=5)

        ttk.Radiobutton(frame, text='Default fragments', name='default_frag', value='default', variable=self.frags_choice).\
            grid(column=0, row=0, sticky=tk.W, padx=5, pady=(3, 1))
        ttk.Radiobutton(frame, text='All rings', name='rings_frag', value='rings', variable=self.frags_choice).\
            grid(column=0, row=1, sticky=tk.W, padx=5, pady=(0, 1))
        # ttk.Radiobutton(frame, text='CCQ fragments', name='ccq_frag', value='ccq', variable=self.frags_choice, state='disabled').\
        #     grid(column=0, row=3, sticky=tk.W, padx=5, pady=(0, 1))
        # ttk.Radiobutton(frame, text='RECAP fragments', name='recap_frag', value='recap', variable=self.frags_choice, state='disabled').\
        #     grid(column=0, row=5, sticky=tk.W, padx=5, pady=(0, 1))
        ttk.Radiobutton(frame, text='Murcko scaffolds (frameworks)', name='murcko_frag',  value='murcko', variable=self.frags_choice).\
            grid(column=0, row=7, sticky=tk.W, padx=5, pady=(0, 1))
        ttk.Radiobutton(frame, text='Automatic fragmentation', name='auto_frag', value='auto', variable=self.frags_choice).\
            grid(column=0, row=8, sticky=tk.W, padx=5, pady=(0, 1))

        cmbbox = ttk.Combobox(frame, name='sdf_path_combobox', width=70, textvariable=self.auto_frags_choice, values=list(self.auto_schemes.keys()), state='readonly')
        cmbbox.grid(column=1, row=8, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=(0, 5))

        ttk.Radiobutton(frame, text='User-defined fragments', name='user_frag', value='user', variable=self.frags_choice).\
            grid(column=0, row=9, sticky=tk.W, padx=5, pady=(0, 1))

        self.__entry_user_frags_path = ttk.Entry(frame, width=70, textvariable=self.user_frags_path)
        self.__entry_user_frags_path.grid(column=0, row=15, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=(0, 3))

        self.__btn_user_frags_path = ttk.Button(frame, text='Browse...', command=self.__select_user_frags)
        self.__btn_user_frags_path.grid(column=2, row=15, sticky=(tk.W), padx=5, pady=(0, 3))

        frame = tk.Frame(self)
        frame.grid(column=0, row=6, columnspan=2)

        self.__btn_calc_contrib = ttk.Button(frame, text='Calculate contributions', command=self.__calc_contributions)
        self.__btn_calc_contrib.grid(column=0, row=0)

        self.columnconfigure(0, weight=1)

        # events
        self.__entry_user_frags_path.bind('<Button-1>', self.__change_to_user)
        self.__entry_user_frags_path.bind('<Button-2>', self.__change_to_user)
        self.__entry_user_frags_path.bind('<Button-3>', self.__change_to_user)
        self.__entry_user_frags_path.bind('<Return>', self.__run_calc_contrib)
        self.__btn_user_frags_path.bind('<Button-1>', self.__change_to_user)
        cmbbox.bind('<<ComboboxSelected>>', self.__change_to_auto)
        cmbbox.bind('<Button-1>', self.__change_to_auto)
        cmbbox.bind('<Button-2>', self.__change_to_auto)
        cmbbox.bind('<Button-3>', self.__change_to_auto)

        parent.add(self, text=tab_name)


class Tab_3(ttk.Frame):

    def _show_models_list(self):

        model_names = self._get_model_list()

        if model_names is not None:

            model_frame = ttk.Labelframe(self, name='model_frame', text='Select models to visualise')
            model_frame.grid(column=1, row=0, sticky=(tk.EW, tk.N), padx=5, pady=5)

            self._models_chkbox = dict()
            for i, m in enumerate(model_names):
                self._models_chkbox[m] = tk.BooleanVar(value=True)
                ttk.Checkbutton(model_frame, name='chk_' + m, variable=self._models_chkbox[m], text=m.upper()).grid(column=0, row=i, sticky=(tk.W), padx=5, pady=(3, 1))

        else:
            if 'model_frame' in self.children.keys():
                self.children['model_frame'].destroy()

    def __run_plot(self, event):
        self.__plot_contributions()

    def __select_save_file_path(self):
        self.save_file_path.set(filedialog.asksaveasfilename(filetypes=[('PNG files', '*.png')],
                                                             defaultextension='.png',
                                                             initialdir=os.path.dirname(self.master.children['tab_1'].sdf_path.get())))

    def __get_selected_contributions(self):
        output = []
        if self.contr_charge.get(): output.append('CHARGE')
        if self.contr_logp.get(): output.append('LOGP')
        if self.contr_overall.get(): output.append('overall')
        if self.contr_hb.get(): output.append('HB')
        if self.contr_ref.get(): output.append('REFRACTIVITY')
        return output

    def _get_selected_models(self):
        output = [k for k, v, in self._models_chkbox.items() if v.get()]
        return output

    def _get_model_list(self):
        if self.master.children['tab_1'].sdf_path.get() != '':
            models_dir = os.path.join(os.path.dirname(self.master.children['tab_1'].sdf_path.get()),
                                      self.master.children['tab_1'].property_field_name.get(),
                                      "models")
            if os.path.isdir(models_dir):
                files = [f[:-4] for f in os.listdir(models_dir) if f.endswith('.pkl')]
                files.remove('scale')
                return files
            else:
                return None
        else:
            return None

    def __plot_contributions(self):

        # at least one checkbox should be checked
        if not self.show_pic.get() and not self.save_pic.get():
            messagebox.showerror('ERROR!', 'You should check at least one option show figure on the screen or '
                                           'save it to the file')
            return

        # check and set output file name
        if self.save_pic.get():
            if self.save_file_path.get() == '':
                messagebox.showerror('ERROR!', 'Specify file name for the output png file')
                return
            else:
                fig_fname = self.save_file_path.get()
        else:
            fig_fname = None


        wd = os.path.join(os.path.dirname(self.master.children['tab_1'].sdf_path.get()), self.master.children['tab_1'].property_field_name.get())
        contr_fname = os.path.join(wd, self.master.children['tab_2'].get_frag_prefix() + '_frag_contributions.txt')

        # models = self.master.children['tab_1'].models_frame.get_selected_models()
        models = self._get_selected_models()

        plot_contributions.main_params(contr_fname=contr_fname,
                                       contr_names=self.__get_selected_contributions(),
                                       fig_fname=fig_fname,
                                       model_names=models,
                                       on_screen=self.show_pic.get(),
                                       min_M=int(self.filter_m.get()),
                                       min_N=int(self.filter_n.get()),
                                       model_type=self.master.children['tab_1'].models_frame.model_type.get())
        pass

    def __init__(self, parent, tab_name):

        ttk.Frame.__init__(self, parent, name='tab_3')

        self.contr_overall = tk.BooleanVar(value=True)
        self.contr_charge = tk.BooleanVar(value=False)
        self.contr_logp = tk.BooleanVar(value=False)
        self.contr_hb = tk.BooleanVar(value=False)
        self.contr_ref = tk.BooleanVar(value=False)

        frame = ttk.Labelframe(self, text='Select contribution types to visualise', name='contributions')
        frame.grid(column=0, row=0, sticky=(tk.EW, tk.N), padx=5, pady=5)

        # select properties
        overall_state = True
        if self.master.children['tab_1'].chemaxon_usage.get() == 'with_chemaxon':
            charge_state, logp_state, hb_state, ref_state = 'normal', 'normal', 'normal', 'normal'
        else:
            charge_state, logp_state, hb_state, ref_state = 'disabled', 'disabled', 'disabled', 'disabled'

        ttk.Checkbutton(frame, variable=self.contr_overall, name='contr_overall', text='overall', state=overall_state).grid(column=0, row=0, sticky=(tk.W), padx=5, pady=(3, 1))
        ttk.Checkbutton(frame, variable=self.contr_charge, name='contr_charge', text='electrostatic (charge)', state=charge_state).grid(column=0, row=1, sticky=(tk.W), padx=5, pady=(0, 1))
        ttk.Checkbutton(frame, variable=self.contr_logp, name='contr_logp', text='hydrophobic (logp)', state=logp_state).grid(column=0, row=2, sticky=(tk.W), padx=5, pady=(0, 1))
        ttk.Checkbutton(frame, variable=self.contr_hb, name='contr_hb', text='hydrogen bonding (hb)', state=hb_state).grid(column=0, row=3, sticky=(tk.W), padx=5, pady=(0, 1))
        ttk.Checkbutton(frame, variable=self.contr_ref, name='contr_ref', text='dispersive (refractivity)', state=ref_state).grid(column=0, row=4, sticky=(tk.W), padx=5, pady=(0, 1))

        output_frame = ttk.Labelframe(self, text='Output options')
        output_frame.grid(column=0, row=5, columnspan=2, sticky=(tk.W, tk.E), padx=5, pady=5)

        self.filter_n = tk.StringVar(value='10')
        self.filter_m = tk.StringVar(value='10')

        ttk.Label(output_frame, text='Minimal occurrence of fragments (N) '.ljust(120, '.')).grid(column=0, row=0, sticky=tk.W, padx=5, pady=(0, 1))
        tk.Spinbox(output_frame, from_=1, to=1000000, textvariable=self.filter_n, width=10).grid(column=1, row=0, sticky=tk.W, padx=5, pady=(0, 1))
        ttk.Label(output_frame, text='Minimal number of molecules containing the same fragment (M) '.ljust(96, '.')).grid(column=0, row=1, sticky=tk.W, padx=5, pady=(0, 1))
        tk.Spinbox(output_frame, from_=1, to=1000000, textvariable=self.filter_m, width=10).grid(column=1, row=1, sticky=tk.W, padx=5, pady=(0, 1))

        self.show_pic = tk.BooleanVar(value=True)
        self.save_pic = tk.BooleanVar(value=True)
        self.save_file_path = tk.StringVar()

        ttk.Checkbutton(output_frame, variable=self.show_pic, text='Show figure in separate window').grid(column=0, row=2, sticky=(tk.W), padx=5, pady=(3, 1))
        ttk.Checkbutton(output_frame, variable=self.save_pic, text='Save figure to file').grid(column=0, row=3, sticky=(tk.W), padx=5, pady=(0, 1))

        self.__save_fig_file_path = ttk.Entry(output_frame, width=70, textvariable=self.save_file_path)
        self.__save_fig_file_path.grid(column=0, row=4, sticky=(tk.W, tk.E), padx=5, pady=(0, 1))
        ttk.Button(output_frame, text='Browse...', command=self.__select_save_file_path).grid(column=1, row=4, sticky=(tk.W), padx=5, pady=(0, 1))

        ttk.Button(self, text='Plot contributions', command=self.__plot_contributions).grid(column=0, row=10, columnspan=2, padx=5, pady=5)

        # events
        self.__save_fig_file_path.bind('<Return>', self.__run_plot)

        parent.add(self, text=tab_name)


def main():

    root = tk.Tk()
    root.title("SPCI - structural and physico-chemical interpretation of QSAR models")

    content = ttk.Frame(root)

    lbl_copyright = ttk.Label(content, text='(c) Pavel Polishchuk 2014-2016')

    tabs = ttk.Notebook(content)
    tab_1 = Tab_1(tabs, 'Build models')
    tab_2 = Tab_2(tabs, 'Calc contributions')
    tab_3 = Tab_3(tabs, 'Plot contributions')

    content.grid(column=0, row=0, sticky=(tk.W, tk.N, tk.E, tk.S))
    tabs.grid(column=0, row=0, sticky=(tk.W, tk.N, tk.E, tk.S))
    lbl_copyright.grid(column=0, row=1, sticky=(tk.W, tk.E, tk.S))

    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)
    content.columnconfigure(0, weight=1)
    content.rowconfigure(0, weight=1)

    root.mainloop()


if __name__ == '__main__':
    main()