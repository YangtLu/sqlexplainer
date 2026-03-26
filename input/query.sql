SELECT city, COUNT(*) AS adult_count
FROM student_info
WHERE age >= 18
GROUP BY city
ORDER BY adult_count DESC;
