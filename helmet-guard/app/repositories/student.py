"""学生仓储：学生档案的查询与批量写入。

职责：封装 students 表的读取、过滤计数与创建。
依赖：sqlalchemy、app.models.identity。
边界：只做数据访问；班级范围过滤由服务层传入的 class_names 参数表达。
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.identity import Student
from app.repositories.base import BaseRepository


class StudentRepository(BaseRepository[Student]):
    """学生档案仓储。"""

    model = Student
    id_field = "student_id"

    def list_with_filters(
        self,
        *,
        keyword: str | None = None,
        class_names: list[str] | None = None,
        college: str | None = None,
        status: str | None = None,
        order_desc: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Student]:
        """按条件分页列出学生。

        Args:
            keyword: 模糊匹配学号/姓名/手机号。
            class_names: 限定班级范围（辅导员场景）；None 表示不限。
            college: 学院精确匹配。
            status: 状态精确匹配。
            order_desc: 是否按学号倒序；默认正序保证确定性。
            limit: 最大返回条数。
            offset: 跳过的记录数。

        Returns:
            学生列表。
        """
        statement = select(Student)
        if class_names is not None:
            statement = statement.where(Student.class_name.in_(class_names))
        if college:
            statement = statement.where(Student.college == college)
        if status:
            statement = statement.where(Student.status == status)
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                (Student.student_id.like(like))
                | (Student.name.like(like))
                | (Student.phone.like(like))
            )
        order_col = Student.student_id.desc() if order_desc else Student.student_id.asc()
        statement = statement.order_by(order_col).limit(limit).offset(offset)
        return list(self.session.execute(statement).scalars().all())

    def count_with_filters(
        self,
        *,
        keyword: str | None = None,
        class_names: list[str] | None = None,
        college: str | None = None,
        status: str | None = None,
    ) -> int:
        """统计符合条件的学生数。

        Args:
            keyword: 模糊匹配学号/姓名/手机号。
            class_names: 限定班级范围；None 表示不限。
            college: 学院精确匹配。
            status: 状态精确匹配。

        Returns:
            匹配的学生总数。
        """
        statement = select(func.count()).select_from(Student)
        if class_names is not None:
            statement = statement.where(Student.class_name.in_(class_names))
        if college:
            statement = statement.where(Student.college == college)
        if status:
            statement = statement.where(Student.status == status)
        if keyword:
            like = f"%{keyword}%"
            statement = statement.where(
                (Student.student_id.like(like))
                | (Student.name.like(like))
                | (Student.phone.like(like))
            )
        return int(self.session.execute(statement).scalar_one())
