Attribute VB_Name = "mod_OneTime_VBA_Export"
Option Compare Database
Option Explicit

Public Sub ExportAllVBA()
    Dim comp As Object
    Dim exportPath As String
    
    exportPath = "C:\Users\miker\OneDrive\Documents\VinylDatabase\ConversionReview\"
    
    ' Ensure folder exists
    If Dir(exportPath, vbDirectory) = "" Then
        MkDir exportPath
    End If
    
    On Error GoTo ErrHandler
    
    ' Access sometimes needs ActiveVBProject to be explicit
    For Each comp In Application.VBE.ActiveVBProject.VBComponents
        Select Case comp.Type
            Case 1  ' Standard module
                comp.Export exportPath & comp.Name & ".bas"
            Case 2  ' Class module
                comp.Export exportPath & comp.Name & ".cls"
            Case 3  ' Form
                comp.Export exportPath & comp.Name & ".frm"
            Case 100 ' Document
                comp.Export exportPath & comp.Name & ".cls"
        End Select
    Next comp
    
    MsgBox "VBA export complete: " & exportPath, vbInformation
    Exit Sub

ErrHandler:
    MsgBox _
        "Export failed. Most likely you need to enable:" & vbCrLf & _
        "File > Options > Trust Center > Trust Center Settings > Macro Settings >" & vbCrLf & _
        """Trust access to the VBA project object model""" & vbCrLf & vbCrLf & _
        "Error " & Err.Number & ": " & Err.Description, _
        vbExclamation
End Sub


