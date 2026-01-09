VERSION 1.0 CLASS
BEGIN
  MultiUse = -1  'True
END
Attribute VB_Name = "Form_sfrmVinylTags"
Attribute VB_GlobalNameSpace = False
Attribute VB_Creatable = True
Attribute VB_PredeclaredId = True
Attribute VB_Exposed = False
Option Compare Database
Option Explicit

Private Sub cmdRemoveTag_Click()
    On Error GoTo EH

    If IsNull(Me!VinylTagID) Then Exit Sub

    If MsgBox("Remove tag '" & Nz(Me!Tag, "") & "' from this record?", _
              vbQuestion + vbYesNo, "Remove Tag") = vbNo Then
        Exit Sub
    End If

    CurrentDb.Execute _
        "DELETE FROM tblVinylTag WHERE VinylTagID=" & CLng(Me!VinylTagID), _
        dbFailOnError

    'Refresh subform list
    Me.Requery

    'Refresh combo on parent form so the removed tag becomes available again
    If CurrentProject.AllForms("LoadForm").IsLoaded Then
        Forms!LoadForm!cboAddTag.Requery
    End If

    Exit Sub

EH:
    MsgBox "Error removing tag: " & Err.Number & " - " & Err.Description, vbExclamation
End Sub


