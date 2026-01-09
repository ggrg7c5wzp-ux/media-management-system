Attribute VB_Name = "modHelpers"
Public Function SortName(ByVal Artist As Variant) As String
    Dim s As String
    Dim lower As String

    s = Trim(Nz(Artist, ""))
    If s = "" Then
        SortName = ""
        Exit Function
    End If

    lower = LCase$(s)

    ' Strip leading articles (The, An, A – any casing)
    If Left$(lower, 4) = "the " Then
        s = Mid$(s, 5)
    ElseIf Left$(lower, 3) = "an " Then
        s = Mid$(s, 4)
    ElseIf Left$(lower, 2) = "a " Then
        s = Mid$(s, 3)
    End If

    SortName = Trim$(s)
End Function

