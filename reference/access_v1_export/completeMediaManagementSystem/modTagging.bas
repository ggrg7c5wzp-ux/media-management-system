Attribute VB_Name = "modTagging"
Option Compare Database
Option Explicit

Public Function CurrentMasterKey() As Variant
    On Error GoTo SafeExit

    If CurrentProject.AllForms("LoadForm").IsLoaded Then
        CurrentMasterKey = Forms!LoadForm!MasterKey
    Else
        CurrentMasterKey = Null
    End If

SafeExit:
End Function

