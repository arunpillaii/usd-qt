#
# Copyright 2017 Pixar
#
# Licensed under the Apache License, Version 2.0 (the "Apache License")
# with the following modification; you may not use this file except in
# compliance with the Apache License and the following modification to it:
# Section 6. Trademarks. is deleted and replaced with:
#
# 6. Trademarks. This License does not grant permission to use the trade
#    names, trademarks, service marks, or product names of the Licensor
#    and its affiliates, except as required to comply with Section 4(c) of
#    the License and to reproduce the content of the NOTICE file.
#
# You may obtain a copy of the Apache License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the Apache License with the above modification is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the Apache License for the specific
# language governing permissions and limitations under the Apache License.
#

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from ._Qt import QtCore, QtWidgets, QtGui

from pxr import Usd, Sdf, Tf

from ._bindings import _AttributeProxy, _DisplayGroupProxy, _MetadataProxy, \
    _MetadataDictKeyProxy, _ObjectProxy, _PrimProxy, _RelationshipProxy, \
    _VariantSetsProxy, _VariantSetProxy

from . import compatability, roles


class OpinionBaseModel(QtCore.QAbstractItemModel):

    class __ResetContext(object):
        """Context manager to ensure model resets if exception is thrown"""

        def __init__(self, model):
            self.model = model

        def __enter__(self):
            self.model.beginResetModel()

        def __exit__(self, exceptionType, exceptionValue, traceBack):
            if exceptionType:
                self.model._Invalidate()
            self.model.endResetModel()

    class __LayoutChangedContext(object):
        """Context manager to ensure layout changes if exception is thrown"""

        def __init__(self, model):
            self.model = model

        def __enter__(self):
            self.model.layoutAboutToBeChanged.emit()

        def __exit__(self, exceptionType, exceptionValue, traceBack):
            if exceptionType:
                self.model._Invalidate()
            self.model.layoutChanged.emit()

    class __Item(object):

        def __init__(self):
            self.parent = None
            self.children = None
            self.row = None
            self.proxy = None
            self.persistentName = None

    def __init__(self, prims, parent=None):
        super(OpinionBaseModel, self).__init__(parent)
        self.ResetPrims(prims)

    def _Invalidate(self):
        """Wipe out all internal data.
        NOT FOR EXTERNAL USE.  Use ResetPrims(None) instead.
        """
        self.__rootItems = []
        self.__proxyToItem = {}
        self.__listeners = None

    def ResetPrims(self, prims):
        """Reset prims invokes a model reset and replaces the current prim
        proxies at the root of the tree with the list provided.

        An empty list or None are valid inputs, which effectively clears the
        the model and shuts down any Tf.Notice listeners"""
        if prims:
            prims = [prim for prim in prims if prim.GetPath() != Sdf.Path('/')]
        if not prims or not all(prims):
            with self.__ResetContext(self):
                self._Invalidate()
        else:
            with self.__LayoutChangedContext(self):
                indexList = self.persistentIndexList()
                indexToPersistentName = {}

                for index in indexList:
                    proxy = self.GetProxyForIndex(index)
                    if proxy in self.__proxyToItem:
                        item = self.__proxyToItem[proxy]
                        indexToPersistentName[index] = item.persistentName
                    else:
                        indexToPersistentName[index] = None

                self._Invalidate()

                stages = set([prim.GetStage() for prim in prims])
                combinedItem = OpinionBaseModel.__Item()
                combinedItem.row = 0
                combinedItem.children = []
                combinedItem.proxy = _PrimProxy(prims)
                combinedItem.persistentName = "./"

                self.__rootItems.append(combinedItem)
                self.__proxyToItem[combinedItem.proxy] = combinedItem
                self.ResyncProxy(combinedItem.proxy)

                persistentNameToItem = {}
                persistentNameToItem[combinedItem.persistentName] = combinedItem
                for proxy in self._TraverseAllDescendents(combinedItem.proxy):
                    item = self.__proxyToItem[proxy]
                    if item.persistentName is not None:
                        persistentNameToItem[item.persistentName] = item

                fromIndices = []
                toIndices = []

                for index in indexToPersistentName:
                    persistentName = indexToPersistentName[index]
                    if persistentName in persistentNameToItem:
                        item = persistentNameToItem[persistentName]
                        newIndex = self.createIndex(item.row, index.column(),
                                                    item.proxy)
                        fromIndices.append(index)
                        toIndices.append(newIndex)
                    else:
                        fromIndices.append(index)
                        toIndices.append(QtCore.QModelIndex())

                self.changePersistentIndexList(fromIndices, toIndices)

                # setup listeners for all stages
                self.__listeners = [Tf.Notice.Register(
                    Usd.Notice.ObjectsChanged, self.__OnObjectsChanged,
                    stage) for stage in stages]

    def _AppendProxy(self, parent, child, persistentName=None):
        """Append a child to the list of parent's children.

        This should not be directly called by external clients of the
        opinion model.  It is provided as a 'protected' method so that
        ResyncProxy can use this to update the tree view topology.
        """
        if not parent in self.__proxyToItem:
            raise Exception("Cannot add child '%s' to parent '%s' not in model." % (repr(
                parent), repr(child)))
        parentItem = self.__proxyToItem[parent]
        item = OpinionBaseModel.__Item()

        item.parent = parentItem
        item.children = []
        item.row = len(item.parent.children)
        item.proxy = child
        item.persistentName = persistentName
        item.parent.children.append(item)
        self.__proxyToItem[item.proxy] = item

    def _TraverseChildren(self, proxy):
        """traverse immediate children of the proxy"""
        for child in self.__proxyToItem[proxy].children:
            yield child.proxy

    def _TraverseAllDescendents(self, proxy):
        """traverse all descendents of the proxy, breadth first traversal"""
        for child in self.__proxyToItem[proxy].children:
            yield child.proxy
            for descendent in self._TraverseAllDescendents(child.proxy):
                yield descendent

    def ResyncProxy(self, proxy):
        """ Return a map of proxies to """
        if type(proxy) is _PrimProxy:
            compositionGroup = _DisplayGroupProxy("Composition")
            metadataGroup = _DisplayGroupProxy("Metadata")
            attributesGroup = _DisplayGroupProxy("Attributes")
            relationshipsGroup = _DisplayGroupProxy("Relationships")
            self._AppendProxy(proxy, compositionGroup, "./Composition")
            self._AppendProxy(proxy, attributesGroup, "./Attributes")
            self._AppendProxy(proxy, relationshipsGroup, "./Relationships")
            self._AppendProxy(proxy, metadataGroup, "./Metadata")

            for compName in ['active', 'instanceable', 'inheritPaths']:
                compProxy = proxy.CreateMetadataProxy(compName)
                self._AppendProxy(compositionGroup, compProxy,
                                  "./Composition/%s" % compName)
            variantSetsProxy = proxy.CreateVariantSetsProxy()
            self._AppendProxy(compositionGroup, variantSetsProxy,
                              "./Composition/VariantSets")
            variantSetNames = variantSetsProxy.GetNames()
            for variantSetName in variantSetNames:
                variantSetProxy = variantSetsProxy.CreateVariantSetProxy(
                    variantSetName)
                self._AppendProxy(variantSetsProxy, variantSetProxy,
                                  "./Composition/VariantSet/%s" % variantSetName)

            for compName in ['references', 'payload', 'specializes']:
                compProxy = proxy.CreateMetadataProxy(compName)
                self._AppendProxy(compositionGroup, compProxy,
                                  "./Composition/%s" % compName)

            for field in proxy.GetMetadataFields():
                if field not in ('payload', 'active', 'instanceable'):
                    metadataProxy = proxy.CreateMetadataProxy(field)
                    self._AppendProxy(metadataGroup, metadataProxy,
                                      "./Metadata/%s" % field)
                    if metadataProxy.GetType() == \
                            Tf.Type.FindByName('VtDictionary'):
                        for key in metadataProxy.GetDictKeys():
                            metadataDictKeyProxy = \
                                metadataProxy.CreateMetadataDictKeyProxy(key)
                            self._AppendProxy(
                                metadataProxy, metadataDictKeyProxy)

            for name in proxy.GetAttributeNames():
                attributeProxy = proxy.CreateAttributeProxy(name)
                self._AppendProxy(attributesGroup, attributeProxy,
                                  "./Attributes/%s" % name)
            for name in proxy.GetRelationshipNames():
                relationshipProxy = proxy.CreateRelationshipProxy(name)
                self._AppendProxy(relationshipsGroup, relationshipProxy,
                                  "./Relationships/%s" % name)

        elif type(proxy) in (_AttributeProxy, _RelationshipProxy):
            print("need to implement resync...", proxy)
        else:
            raise Exception(
                "Only prims and property proxies can be resynced. '%s'" % repr(proxy))

    def ChangeInfoForProxy(self, proxy):
        if not proxy:
            raise Exception("cannot change info for expired proxy.")
        elif type(proxy) is _PrimProxy:
            # TODO:  Special handling for prim specific data
            row = self.__proxyToItem[proxy].row
            columnCount = self.columnCount(QtCore.QModelIndex())
            compatability.EmitDataChanged(self,
                                          self.createIndex(row, 0, proxy),
                                          self.createIndex(row, columnCount, proxy))
        elif type(proxy) is _AttributeProxy:
            # TODO:  Special handling for prim specific data
            row = self.__proxyToItem[proxy].row
            columnCount = self.columnCount(QtCore.QModelIndex())
            compatability.EmitDataChanged(self,
                                          self.createIndex(row, 0, proxy),
                                          self.createIndex(row, columnCount, proxy))

    def __OnObjectsChanged(self, notice, sender):
        # explore abstracting change processing into central helper class
        changeInfoPaths = notice.GetChangedInfoOnlyPaths()
        resyncPaths = notice.GetResyncedPaths()

        if resyncPaths:
            resyncProxies = [proxy for proxy in self.__proxyToItem
                             if isinstance(proxy, _ObjectProxy) and
                             proxy.ContainsPathOrDescendent(resyncPaths)]
            if resyncProxies:
                # it seems fast enough to just dump and rebuild on resync
                # operations.
                if len(self.__rootItems) > 0:
                    self.ResetPrims(self.__rootItems[0].proxy.GetPrims())
        if changeInfoPaths:
            changeInfoProxies = [proxy for proxy in self.__proxyToItem
                                 if isinstance(proxy, _ObjectProxy) and
                                 proxy.ContainsPath(changeInfoPaths)]
            if changeInfoPaths:
                for proxy in changeInfoProxies:
                    self.ChangeInfoForProxy(proxy)

    def GetProxyForIndex(self, modelIndex):
        if not modelIndex.isValid():
            return None
        else:
            if not modelIndex.internalPointer().expired:
                return modelIndex.internalPointer()

    def rowCount(self, parent):
        if not parent.isValid():
            return len(self.__rootItems)
        proxy = parent.internalPointer()
        item = self.__proxyToItem[proxy]
        return len(item.children)

    def parent(self, modelIndex):
        if not modelIndex.isValid():
            return QtCore.QModelIndex()
        proxy = modelIndex.internalPointer()
        item = self.__proxyToItem[proxy]
        if item in self.__rootItems:
            return QtCore.QModelIndex()
        return self.createIndex(item.row, 0, item.parent.proxy)

    def columnCount(self, parent):
        return 1

    def data(self, modelIndex, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.DisplayRole:
            data = self.GetProxyForIndex(modelIndex)
            if type(data) is _PrimProxy:
                return ", ".join(data.GetNames())
            elif type(data) == _AttributeProxy:
                return data.GetName()
            elif type(data) is _MetadataProxy:
                return data.GetName()
            elif type(data) is _DisplayGroupProxy:
                return data.GetName()
            elif type(data) is _RelationshipProxy:
                return data.GetName()

    def index(self, row, column, parent=QtCore.QModelIndex()):
        if not parent.isValid():
            return self.createIndex(row, column, self.__rootItems[row].proxy)
        else:
            parentProxy = parent.internalPointer()
            parentItem = self.__proxyToItem[parentProxy]
            childItem = parentItem.children[row]
        return self.createIndex(row, column, childItem.proxy)


class OpinionStandardModel(OpinionBaseModel):
    FallbackColor = QtGui.QBrush(QtGui.QColor(222, 158, 46))
    TimeSamplesTextColor = QtGui.QBrush(QtGui.QColor(177, 207, 153))
    DefaultTextColor = QtGui.QBrush(QtGui.QColor(135, 206, 250))
    NoValueTextColor = QtGui.QBrush(QtGui.QColor(140, 140, 140))
    ValueClipsTextColor = QtGui.QBrush(QtGui.QColor(230, 150, 230))

    Name = "Name"
    Value = "Value"
    TypeName = "Type Name"

    def __init__(self, prims, columns=None, timeCode=Usd.TimeCode.Default(), parent=None):
        super(OpinionStandardModel, self).__init__(prims, parent)
        self.__timeCode = timeCode
        if not columns:
            # By default show all possible columns.
            self.columns = [OpinionStandardModel.Name,
                            OpinionStandardModel.TypeName,
                            OpinionStandardModel.Value]
        else:
            self.columns = columns

    def columnCount(self, parent):
        return len(self.columns)

    def headerData(self, section, orietation, role):
        if role == QtCore.Qt.DisplayRole:
            column = self.columns[section]
            if column == OpinionStandardModel.Value:
                return "Value @ %s" % str(self.__timeCode)
            else:
                return self.columns[section]

    def _GetDataForDisplayGroup(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return proxy.GetName()
        elif role == roles.EditorHintRole:
            if column == OpinionStandardModel.Name:
                return roles.EditorHintTab()

    def _GetDataForAttribute(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return proxy.GetName()
            elif column == OpinionStandardModel.TypeName:
                return str(proxy.GetTypeName())
            elif column == OpinionStandardModel.Value:
                value = proxy.Get(self.__timeCode)
                if hasattr(value, '_isVtArray') and value._isVtArray:
                    if len(value) == 0:
                        return "[]"
                    elif len(value) == 1:
                        return "[%s]" % str(value[0])
                    else:
                        return "[%s, ...]" % (str(value[0]))
                return str(value) if value is not None else ''
        elif role == QtCore.Qt.EditRole:
            if column == OpinionStandardModel.Value:
                return proxy.Get(self.__timeCode)
        elif role == QtCore.Qt.ToolTipRole:
            return "[%s] %s" % (str(proxy.GetTypeName()), proxy.GetDocumentation())
        elif role == roles.EditorHintRole:
            if column == OpinionStandardModel.Value:
                tfType = proxy.GetTypeName().type
                if tfType == Tf.Type.FindByName("TfToken"):
                    allowedValues = proxy.GetAllowedTokens()
                    if len(allowedValues) > 0:
                        return roles.EditorHintTextCombo(allowedValues)
                return roles.EditorHintBasicValue(tfType)

    def _GetDataForPrim(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return ", ".join(proxy.GetNames())
        elif role == roles.EditorHintRole:
            if column == OpinionStandardModel.Name:
                return roles.EditorHintTab()

    def _GetDataForMetadata(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                name = proxy.GetName()
                return name if name != 'inheritPaths' else 'inherits'
            elif column == OpinionStandardModel.TypeName:
                return proxy.GetType().typeName
            elif column == OpinionStandardModel.Value:
                value = proxy.GetValue()
                if type(value) == Sdf.PathListOp:
                    return [str(p) for p in value.GetAddedOrExplicitItems()]
                if type(value) == Sdf.Payload:
                    return "@%s@<%s>" % (value.assetPath, value.primPath)
                return value
        elif role == QtCore.Qt.EditRole:
            if column == OpinionStandardModel.Value:
                return proxy.GetValue()
        elif role == roles.EditorHintRole:
            if column == OpinionStandardModel.Value:
                return roles.EditorHintBasicValue(proxy.GetType())

    def _GetDataForMetadataDictKey(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return proxy.GetEntryName()
            elif column == OpinionStandardModel.TypeName:
                return proxy.GetType().typeName
            elif column == OpinionStandardModel.Value:
                value = proxy.GetValue()
                return value
        elif role == QtCore.Qt.EditRole:
            if column == OpinionStandardModel.Value:
                return proxy.GetValue()
        elif role == roles.EditorHintRole:
            if column == OpinionStandardModel.Value:
                return roles.EditorHitBasicValue(proxy.GetType())

    def _GetDataForRelationship(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return proxy.GetName()
            if column == OpinionStandardModel.TypeName:
                return "rel"
            if column == OpinionStandardModel.Value:
                return [str(t) for t in proxy.GetTargets()]
        elif role == QtCore.Qt.ToolTipRole:
            if column == OpinionStandardModel.Name:
                return proxy.GetDocumentation()
            elif column == OpinionStandardModel.Value:
                return "\n".join([str(t) for t in proxy.GetForwardedTargets()])

    def _GetDataForVariantSets(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return "variants"

    def _GetDataForVariantSet(self, proxy, column, role):
        if role == QtCore.Qt.DisplayRole:
            if column == OpinionStandardModel.Name:
                return proxy.GetName()
            if column == OpinionStandardModel.TypeName:
                return "string"
            if column == OpinionStandardModel.Value:
                return proxy.GetVariantSelection()
        elif role == QtCore.Qt.EditRole:
            if column == OpinionStandardModel.Value:
                return proxy.GetVariantSelection()
        elif role == roles.EditorHintRole:
            allowedValues = proxy.GetVariantNames()
            return roles.EditorHintTextCombo(allowedValues)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        proxy = self.GetProxyForIndex(index)
        column = self.columns[index.column()]
        proxyType = type(proxy)

        if proxyType == _DisplayGroupProxy:
            return self._GetDataForDisplayGroup(proxy, column, role)
        if proxyType == _PrimProxy:
            return self._GetDataForPrim(proxy, column, role)
        elif proxyType == _AttributeProxy:
            return self._GetDataForAttribute(proxy, column, role)
        elif proxyType == _MetadataProxy:
            return self._GetDataForMetadata(proxy, column, role)
        elif proxyType == _MetadataDictKeyProxy:
            return self._GetDataForMetadataDictKey(proxy, column, role)
        elif proxyType == _VariantSetProxy:
            return self._GetDataForVariantSet(proxy, column, role)
        elif proxyType == _VariantSetsProxy:
            return self._GetDataForVariantSets(proxy, column, role)
        elif proxyType == _RelationshipProxy:
            return self._GetDataForRelationship(proxy, column, role)

    def setData(self, index, value, role):
        """ Call the approriate set method for the EditRole proxy 
        Traditionally, we would emit the "dataChanged" signal in the setData
        method directly. Instead, we are letting Usd's change notification 
        emit the signal so that we robustly handle all edits from all sources
        without emitting the signal twice."""
        if role == QtCore.Qt.EditRole:
            column = self.columns[index.column()]
            if column == OpinionStandardModel.Value:
                proxy = self.GetProxyForIndex(index)
                if type(proxy) is _AttributeProxy:
                    valuePy = compatability.ResolveValue(value)
                    proxy.Set(valuePy, self.__timeCode)
                    return True
                elif type(proxy) is _MetadataProxy:
                    valuePy = compatability.ResolveValue(value)
                    proxy.SetValue(valuePy)
                    return True
                elif type(proxy) is _MetadataDictKeyProxy:
                    valuePy = compatability.ResolveValue(value)
                    proxy.SetValue(valuePy)
                    return True
                elif type(proxy) is _VariantSetProxy:
                    valuePy = compatability.ResolveValue(value)
                    proxy.SetVariantSelection(valuePy)
                    return True
                else:
                    raise Exception("Unsupported type.")
            else:
                raise Exception("Unsupported edit column.")
        return False

    def ClearData(self, index):
        proxy = self.GetProxyForIndex(index)
        if type(proxy) is _AttributeProxy:
            proxy.Clear()
        elif type(proxy) is _RelationshipProxy:
            proxy.ClearTargets()
        elif type(proxy) is _MetadataDictKeyProxy:
            proxy.ClearValue()
        elif type(proxy) is _MetadataProxy:
            proxy.ClearValue()
        elif type(proxy) is _VariantSetProxy:
            proxy.ClearVariantSelection()

    def ClearAtTime(self, index):
        proxy = self.GetProxyForIndex(index)
        if type(proxy) is _AttributeProxy:
            proxy.ClearAtTime(self.__timeCode)

    def BlockData(self, index):
        proxy = self.GetProxyForIndex(index)
        if type(proxy) is _AttributeProxy:
            proxy.BlockValue()
        elif type(proxy) is _RelationshipProxy:
            proxy.BlockTargets()

    def flags(self, index):
        column = self.columns[index.column()]
        if column == OpinionStandardModel.Value:
            return QtCore.Qt.ItemIsEditable | \
                super(OpinionStandardModel, self).flags(index)
        return super(OpinionStandardModel, self).flags(index)

if __name__ == '__main__':
    import sys
    from ._Qt import QtWidgets

    app = QtWidgets.QApplication(sys.argv)

    stage = Usd.Stage.Open('testenv/testUsdQtOpinionModel/simple.usda')
    prim = stage.GetPrimAtPath('/MyPrim1/Child1')
    prim2 = stage.GetPrimAtPath('/MyPrim1/Child2')
    model = OpinionStandardModel([prim, prim2])
    tv = QtWidgets.QTreeView()
    tv.setModel(model)
    tv.show()
    sys.exit(app.exec_())
