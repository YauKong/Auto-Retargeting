from PySide2 import QtWidgets, QtCore, QtGui
from shiboken2 import wrapInstance
from importlib import reload
import maya.OpenMayaUI as omui
import maya.cmds as cmds
import json
import os
import retargeting_main as retarget

reload(retarget)


def get_maya_window():
    """
    Retrieves the main Maya window as a QWidget.

    Returns:
        QWidget: The Maya main window.
    """
    main_window_ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(main_window_ptr), QtWidgets.QWidget)


class ComboBoxDelegate(QtWidgets.QStyledItemDelegate):
    """
    A custom delegate that provides an editable QComboBox as the editor.
    The combo box is pre-populated with all non-empty items from the current column.
    """
    def __init__(self, parent=None):
        super(ComboBoxDelegate, self).__init__(parent)

    def createEditor(self, parent, option, index):
        combo = QtWidgets.QComboBox(parent)
        combo.setEditable(True)
        # Collect all non-empty items from the column.
        model = index.model()
        col = index.column()
        items = set()
        for row in range(model.rowCount()):
            val = model.index(row, col).data(QtCore.Qt.DisplayRole)
            if val is not None and val != "":
                items.add(val)
        items = list(items)
        items.sort()
        combo.addItems(items)
        # Set the current text.
        current_value = index.data(QtCore.Qt.EditRole) or ""
        combo.setCurrentText(current_value)
        return combo

    def setEditorData(self, editor, index):
        value = index.data(QtCore.Qt.EditRole) or ""
        editor.setCurrentText(value)

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText(), QtCore.Qt.EditRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class MappingTable(QtWidgets.QTableWidget):
    """
    A custom table widget for displaying mapping entries.
    This table supports cell-level dragging (with swapping) and per-cell editing via a custom delegate.
    """
    def __init__(self, parent=None):
        super(MappingTable, self).__init__(parent)
        self.setColumnCount(3)
        self.setHorizontalHeaderLabels(["Moveable", "Source Joint", "Target Rig Control"])
        # Change selection behavior to individual cells.
        self.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectItems)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        # Enable drag and drop (we override dropEvent to swap cell contents within a column).
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.DragDrop)
        self._start_index = None

    def mousePressEvent(self, event):
        self._start_index = self.indexAt(event.pos())
        super(MappingTable, self).mousePressEvent(event)

    def dropEvent(self, event):
        if self._start_index is None:
            event.ignore()
            return
        pos = event.pos()
        target_index = self.indexAt(pos)
        # Only swap if the drop is within the same column.
        if (target_index.isValid() and self._start_index.isValid() and 
                self._start_index.column() == target_index.column()):
            source_item = self.item(self._start_index.row(), self._start_index.column())
            target_item = self.item(target_index.row(), target_index.column())
            if source_item and target_item:
                temp = source_item.text()
                source_item.setText(target_item.text())
                target_item.setText(temp)
        event.accept()
        self._start_index = None


class RetargetingTool(QtWidgets.QDialog):
    def __init__(self, parent=None):
        """
        Initializes the RetargetingTool dialog UI.
        """
        super(RetargetingTool, self).__init__(parent)
        self.setWindowTitle("Maya Anim Retarget")
        main_layout = QtWidgets.QVBoxLayout(self)

        # Menu Bar
        self.menu_bar = QtWidgets.QMenuBar(self)
        file_menu = self.menu_bar.addMenu("File")
        load_action = QtWidgets.QAction("Load JSON", self)
        load_action.triggered.connect(self.load_json_file)
        file_menu.addAction(load_action)
        save_action = QtWidgets.QAction("Save JSON", self)
        save_action.triggered.connect(self.save_json_file)
        file_menu.addAction(save_action)
        main_layout.setMenuBar(self.menu_bar)

        # Namespace Inputs
        self.joint_namespace_label = QtWidgets.QLabel("Source Joint Namespace:")
        self.joint_namespace_edit = QtWidgets.QLineEdit()
        self.rig_namespace_label = QtWidgets.QLabel("Target Rig Control Namespace:")
        self.rig_namespace_edit = QtWidgets.QLineEdit()
        main_layout.addWidget(self.joint_namespace_label)
        main_layout.addWidget(self.joint_namespace_edit)
        main_layout.addWidget(self.rig_namespace_label)
        main_layout.addWidget(self.rig_namespace_edit)

        # Import Options Layout (Import As and Node Type)
        import_layout = QtWidgets.QHBoxLayout()
        self.import_as_label = QtWidgets.QLabel("Import As:")
        import_layout.addWidget(self.import_as_label)
        self.import_as_combo = QtWidgets.QComboBox()
        self.import_as_combo.addItems(["Source Joint", "Target Rig Control"])
        import_layout.addWidget(self.import_as_combo)
        # New: Node Type selection
        self.node_type_label = QtWidgets.QLabel("Node Type:")
        import_layout.addWidget(self.node_type_label)
        self.node_type_combo = QtWidgets.QComboBox()
        self.node_type_combo.addItems(["Joint", "Curve"])
        import_layout.addWidget(self.node_type_combo)
        # Import button
        self.import_selected_button = QtWidgets.QPushButton("Import Selected Objects")
        self.import_selected_button.clicked.connect(self.import_selected_objects)
        import_layout.addWidget(self.import_selected_button)
        import_layout.addStretch()
        main_layout.addLayout(import_layout)

        # Mapping Table (replaces previous QTreeWidget)
        self.mapping_table = MappingTable()
        # Set our custom delegate for columns 1 and 2.
        self.mapping_table.setItemDelegateForColumn(1, ComboBoxDelegate(self.mapping_table))
        self.mapping_table.setItemDelegateForColumn(2, ComboBoxDelegate(self.mapping_table))
        main_layout.addWidget(self.mapping_table)
        # Connect selection change signal to highlight scene objects.
        self.mapping_table.itemSelectionChanged.connect(self.highlight_selected_objects)

        # Add/Delete Buttons Layout
        btn_layout = QtWidgets.QHBoxLayout()
        self.add_mapping_button = QtWidgets.QPushButton("+")
        self.add_mapping_button.setToolTip("Add a new mapping entry")
        self.add_mapping_button.clicked.connect(self.add_mapping_entry)
        btn_layout.addWidget(self.add_mapping_button)
        self.delete_mapping_button = QtWidgets.QPushButton("–")
        self.delete_mapping_button.setToolTip("Delete selected mapping entry(ies)")
        self.delete_mapping_button.clicked.connect(self.delete_mapping_entries)
        btn_layout.addWidget(self.delete_mapping_button)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

        # Execute Button
        self.action_button = QtWidgets.QPushButton("Execute")
        self.action_button.clicked.connect(self.on_action_button_clicked)
        main_layout.addWidget(self.action_button)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.WindowStaysOnTopHint)
        self.config_file_path = None

    def standardize_namespace(self, ns):
        ns = ns.strip()
        if ns.endswith(":"):
            ns = ns[:-1]
        return ns

    def populate_mapping_table(self, json_data):
        """
        Populates the MappingTable with the provided JSON data.
        """
        self.mapping_table.setRowCount(0)
        for entry in json_data:
            row = self.mapping_table.rowCount()
            self.mapping_table.insertRow(row)
            # Column 0: Moveable checkbox.
            checkbox = QtWidgets.QCheckBox()
            checkbox.setChecked(entry.get("move_able", False))
            self.mapping_table.setCellWidget(row, 0, checkbox)
            # Column 1: Source Joint.
            source_item = QtWidgets.QTableWidgetItem(entry.get("source_joint", ""))
            source_item.setFlags(source_item.flags() | QtCore.Qt.ItemIsEditable | 
                                   QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
            self.mapping_table.setItem(row, 1, source_item)
            # Column 2: Target Rig Control.
            target_item = QtWidgets.QTableWidgetItem(entry.get("target_control", ""))
            target_item.setFlags(target_item.flags() | QtCore.Qt.ItemIsEditable | 
                                   QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
            self.mapping_table.setItem(row, 2, target_item)

    def import_selected_objects(self):
        """
        Recursively imports objects under the selected Maya items into the column defined by the dropdown.
        Uses the Node Type selection to distinguish between "Joint" and "Curve" (or others).
        For each found object, if it isn’t already in that column, the function fills an empty cell if available;
        otherwise, it creates a new row.
        """
        # Determine which column to fill.
        import_as = self.import_as_combo.currentText()
        col_index = 1 if import_as == "Source Joint" else 2
        # Get desired node type.
        selected_node_type = self.node_type_combo.currentText()

        selected_objects = cmds.ls(selection=True)
        if not selected_objects:
            QtWidgets.QMessageBox.warning(self, "No Selection", "No objects selected in the scene.")
            return

        all_objects = []
        if selected_node_type == "Joint":
            # For joints, use similar logic as before.
            for obj in selected_objects:
                if cmds.nodeType(obj) == "joint":
                    all_objects.append(obj)
                else:
                    joints = cmds.listRelatives(obj, allDescendents=True, type="joint") or []
                    all_objects.extend(joints)
        elif selected_node_type == "Curve":
            # For curves, recursively search for transforms that have a nurbsCurve shape.
            for obj in selected_objects:
                # Check if the selected object itself is a transform with a curve shape.
                shapes = cmds.listRelatives(obj, shapes=True, fullPath=True) or []
                for shape in shapes:
                    if cmds.nodeType(shape) == "nurbsCurve":
                        all_objects.append(obj)
                        break
                # Also search recursively under the object.
                child_transforms = cmds.listRelatives(obj, allDescendents=True, type="transform") or []
                for trans in child_transforms:
                    shapes = cmds.listRelatives(trans, shapes=True, fullPath=True) or []
                    for shape in shapes:
                        if cmds.nodeType(shape) == "nurbsCurve":
                            all_objects.append(trans)
                            break

        # Remove duplicates.
        all_objects = list(set(all_objects))
        if not all_objects:
            QtWidgets.QMessageBox.warning(self, "No Objects", 
                                          f"No {selected_node_type.lower()} objects found under the selected item(s).")
            return

        # Fill in the mapping table.
        for obj in all_objects:
            # Skip if already exists in the target column.
            exists = False
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, col_index)
                if item and item.text().strip() == obj:
                    exists = True
                    break
            if exists:
                continue

            # Try to fill an empty cell.
            filled = False
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, col_index)
                if item is None or item.text().strip() == "":
                    if item is None:
                        new_item = QtWidgets.QTableWidgetItem(obj)
                        new_item.setFlags(new_item.flags() | QtCore.Qt.ItemIsEditable |
                                          QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                        self.mapping_table.setItem(row, col_index, new_item)
                    else:
                        item.setText(obj)
                    filled = True
                    break

            # If no empty cell was found, create a new row.
            if not filled:
                row = self.mapping_table.rowCount()
                self.mapping_table.insertRow(row)
                checkbox = QtWidgets.QCheckBox()
                checkbox.setChecked(False)
                self.mapping_table.setCellWidget(row, 0, checkbox)
                if col_index == 1:
                    source_item = QtWidgets.QTableWidgetItem(obj)
                    source_item.setFlags(source_item.flags() | QtCore.Qt.ItemIsEditable |
                                           QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 1, source_item)
                    target_item = QtWidgets.QTableWidgetItem("")
                    target_item.setFlags(target_item.flags() | QtCore.Qt.ItemIsEditable |
                                           QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 2, target_item)
                else:
                    source_item = QtWidgets.QTableWidgetItem("")
                    source_item.setFlags(source_item.flags() | QtCore.Qt.ItemIsEditable |
                                           QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 1, source_item)
                    target_item = QtWidgets.QTableWidgetItem(obj)
                    target_item.setFlags(target_item.flags() | QtCore.Qt.ItemIsEditable |
                                           QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 2, target_item)


        # Now, for each found object, try to fill an empty cell in the designated column;
        # if none is available, create a new row.
        for obj in all_objects:
            # Skip if the object already exists in the target column.
            exists = False
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, col_index)
                if item and item.text().strip() == obj:
                    exists = True
                    break
            if exists:
                continue

            # Attempt to fill an empty cell in the specified column.
            filled = False
            for row in range(self.mapping_table.rowCount()):
                item = self.mapping_table.item(row, col_index)
                if item is None or item.text().strip() == "":
                    if item is None:
                        new_item = QtWidgets.QTableWidgetItem(obj)
                        new_item.setFlags(new_item.flags() | QtCore.Qt.ItemIsEditable |
                                        QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                        self.mapping_table.setItem(row, col_index, new_item)
                    else:
                        item.setText(obj)
                    filled = True
                    break

            # If no empty cell was found, create a new row.
            if not filled:
                row = self.mapping_table.rowCount()
                self.mapping_table.insertRow(row)
                # Create the moveable checkbox in column 0.
                checkbox = QtWidgets.QCheckBox()
                checkbox.setChecked(True)
                self.mapping_table.setCellWidget(row, 0, checkbox)
                if col_index == 1:
                    source_item = QtWidgets.QTableWidgetItem(obj)
                    source_item.setFlags(source_item.flags() | QtCore.Qt.ItemIsEditable |
                                        QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 1, source_item)
                    # Leave the target cell empty.
                    target_item = QtWidgets.QTableWidgetItem("")
                    target_item.setFlags(target_item.flags() | QtCore.Qt.ItemIsEditable |
                                        QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 2, target_item)
                else:
                    source_item = QtWidgets.QTableWidgetItem("")
                    source_item.setFlags(source_item.flags() | QtCore.Qt.ItemIsEditable |
                                        QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 1, source_item)
                    target_item = QtWidgets.QTableWidgetItem(obj)
                    target_item.setFlags(target_item.flags() | QtCore.Qt.ItemIsEditable |
                                        QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
                    self.mapping_table.setItem(row, 2, target_item)

    def add_mapping_entry(self):
        """
        Manually adds a new mapping entry (row) to the table.
        """
        row = self.mapping_table.rowCount()
        self.mapping_table.insertRow(row)
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(True)
        self.mapping_table.setCellWidget(row, 0, checkbox)
        source_item = QtWidgets.QTableWidgetItem("")
        source_item.setFlags(source_item.flags() | QtCore.Qt.ItemIsEditable |
                               QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
        self.mapping_table.setItem(row, 1, source_item)
        target_item = QtWidgets.QTableWidgetItem("")
        target_item.setFlags(target_item.flags() | QtCore.Qt.ItemIsEditable |
                               QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled)
        self.mapping_table.setItem(row, 2, target_item)
        self.mapping_table.setCurrentCell(row, 1)

    def delete_mapping_entries(self):
        """
        Deletes all rows corresponding to the currently selected cells.
        """
        rows_to_delete = set()
        for item in self.mapping_table.selectedItems():
            rows_to_delete.add(item.row())
        for row in sorted(rows_to_delete, reverse=True):
            self.mapping_table.removeRow(row)

    def highlight_selected_objects(self):
        """
        When a cell in the Source Joint or Target Rig Control column is selected,
        highlights the corresponding scene object (if it exists) in Maya.
        """
        selected_items = self.mapping_table.selectedItems()
        objects_to_select = []
        for item in selected_items:
            if item.column() in (1, 2):
                obj_name = item.text().strip()
                if obj_name and cmds.objExists(obj_name):
                    objects_to_select.append(obj_name)
        if objects_to_select:
            cmds.select(objects_to_select, replace=True)
        else:
            cmds.select(clear=True)

    def on_action_button_clicked(self):
        """
        Collects data from the table and namespace fields, then calls the retargeting function.
        """
        joint_namespace = self.standardize_namespace(self.joint_namespace_edit.text())
        rig_namespace = self.standardize_namespace(self.rig_namespace_edit.text())
        mappings = []
        for row in range(self.mapping_table.rowCount()):
            checkbox = self.mapping_table.cellWidget(row, 0)
            move_able = checkbox.isChecked() if checkbox else False
            source_joint = (self.mapping_table.item(row, 1).text() 
                            if self.mapping_table.item(row, 1) is not None else "")
            target_control = (self.mapping_table.item(row, 2).text() 
                              if self.mapping_table.item(row, 2) is not None else "")
            mappings.append({
                "source_joint": source_joint,
                "target_control": target_control,
                "move_able": move_able
            })
        retarget.apply_retargeting(rig_namespace, joint_namespace, mappings, self.config_file_path)
        print("Executing retargeting with:")
        print("Source Namespace:", joint_namespace)
        print("Target Namespace:", rig_namespace)
        print("Mappings:", mappings)

    def load_json_file(self):
        """
        Loads a JSON file and populates the mapping table.
        """
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load JSON File", "", "JSON Files (*.json)")
        print("Loading JSON file from:", file_path)
        if file_path:
            try:
                with open(file_path, "r") as f:
                    json_data = json.load(f)
                    self.populate_mapping_table(json_data)
                    self.config_file_path = file_path
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to load JSON file: {e}")
        self.raise_()
        self.activateWindow()

    def save_json_file(self):
        """
        Saves the current mapping table data to a JSON file.
        """
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save JSON File", "", "JSON Files (*.json)")
        if file_path:
            try:
                json_data = []
                for row in range(self.mapping_table.rowCount()):
                    checkbox = self.mapping_table.cellWidget(row, 0)
                    move_able = checkbox.isChecked() if checkbox else False
                    source_joint = (self.mapping_table.item(row, 1).text() 
                                    if self.mapping_table.item(row, 1) is not None else "")
                    target_control = (self.mapping_table.item(row, 2).text() 
                                      if self.mapping_table.item(row, 2) is not None else "")
                    json_data.append({
                        "source_joint": source_joint,
                        "target_control": target_control,
                        "move_able": move_able
                    })
                with open(file_path, "w") as f:
                    json.dump(json_data, f, indent=4)
            except Exception as e:
                QtWidgets.QMessageBox.critical(self, "Error", f"Failed to save JSON file: {e}")
        self.raise_()
        self.activateWindow()


if __name__ == "__main__":
    parent = get_maya_window()
    ui = RetargetingTool(parent)
    ui.show()
